package app.nonnawatch.listener

import android.Manifest
import android.annotation.SuppressLint
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.net.wifi.WifiManager
import android.os.BatteryManager
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import android.util.Log
import androidx.annotation.RequiresPermission
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat
import app.nonnawatch.core.Room
import app.nonnawatch.listener.audio.AudioChunk
import app.nonnawatch.listener.audio.MicRecorder
import app.nonnawatch.listener.audio.peakPercent
import app.nonnawatch.listener.hub.BatteryReading
import app.nonnawatch.listener.hub.HubConfig
import app.nonnawatch.listener.hub.HubLink
import app.nonnawatch.listener.hub.OkHttpHubSockets
import app.nonnawatch.listener.hub.deviceModel
import app.nonnawatch.listener.hub.hubHttpClient
import app.nonnawatch.listener.settings.ListenerSettings
import app.nonnawatch.listener.settings.PrefsSettingsStore
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.launch

/**
 * Keeps the microphone on and streams it to the hub, also with the screen off and the app closed.
 *
 * A normal app is frozen soon after it leaves the screen. A foreground service keeps running, and
 * Android makes it show a notification so the person always knows the microphone is on. It is
 * declared with type "microphone" in the manifest, which Android 14+ requires.
 *
 * While it runs it holds a partial WakeLock (the processor stays awake with the screen off) and a
 * WifiLock (Wi-Fi does not go to sleep), as docs/api-contract.md asks.
 *
 * Each second of audio goes to the hub through [HubLink] and is then dropped; nothing is saved.
 */
class ListenerService : Service() {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private val recorder = MicRecorder()
    private val settingsStore by lazy { PrefsSettingsStore(this) }
    private var running: Job? = null
    private var wakeLock: PowerManager.WakeLock? = null
    private var wifiLock: WifiManager.WifiLock? = null

    /** Why the service stopped by itself; shown on the screen. Null when the user tapped Stop. */
    private var stopProblem: String? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val settings = settingsStore.load().cleaned()

        // A service started with startForegroundService must call startForeground within seconds,
        // even if it then stops, or Android ends the app. So this comes before any other check.
        if (!goForeground(settings.room)) {
            stopWith("Android did not let the listener start")
            return START_NOT_STICKY
        }
        settings.problem()?.let { problem ->
            stopWith(problem)
            return START_NOT_STICKY
        }
        if (!hasMicPermission()) {
            stopWith("the microphone permission is missing")
            return START_NOT_STICKY
        }
        if (running?.isActive != true) startListening(settings)

        // Not sticky: if Android kills the service, it does not restart it by itself. A restarted
        // service starts in the background, where Android gives it no microphone. Someone opens
        // the app and taps Start again (docs/api-contract.md, notes for the listener app).
        return START_NOT_STICKY
    }

    override fun onDestroy() {
        scope.cancel() // stops the recording and closes the link to the hub with a normal close
        releaseLocks()
        ServiceStateHolder.set(ServiceState.Stopped(stopProblem))
        super.onDestroy()
    }

    // onStartCommand checks the permission before calling this.
    @SuppressLint("MissingPermission")
    private fun startListening(settings: ListenerSettings) {
        holdLocks()
        val paused = ServiceStateHolder.paused.apply { value = false }
        val link = HubLink(
            config = HubConfig(
                url = settings.hubUrl,
                token = settings.token,
                room = settings.room,
                deviceId = settingsStore.deviceId(),
                appVersion = BuildConfig.VERSION_NAME,
                deviceModel = deviceModel(Build.MANUFACTURER, Build.MODEL),
            ),
            sockets = OkHttpHubSockets(httpClient),
            paused = paused,
            battery = ::readBattery,
            log = { Log.i(TAG, it) },
        )
        val mic = MutableStateFlow<MicState>(MicState.Recording(secondsRecorded = 0, levelPercent = 0))

        running = scope.launch {
            launch {
                combine(mic, link.state) { micState, hubState ->
                    ServiceState.Running(settings.room, micState, hubState)
                }.collect { ServiceStateHolder.set(it) }
            }
            launch {
                val reason = link.run() // returns only if the hub refuses this phone for good
                stopWith(reason)
            }

            var seconds = 0L
            // collectLatest cancels the recording when the switch flips to paused, which releases
            // the microphone: Android's microphone indicator turns off.
            paused.collectLatest { isPaused ->
                showNotification(settings.room, isPaused)
                if (isPaused) {
                    mic.value = MicState.Paused
                    return@collectLatest
                }
                mic.value = MicState.Recording(seconds, levelPercent = 0)
                record(
                    onChunk = { chunk ->
                        seconds += 1
                        link.send(chunk) // the chunk is dropped after this
                        mic.value = MicState.Recording(seconds, chunk.peakPercent())
                    },
                    onProblem = { message -> mic.value = MicState.Problem(message) },
                )
            }
        }
    }

    /** Records until cancelled. If the microphone fails, says so and tries again. */
    @RequiresPermission(Manifest.permission.RECORD_AUDIO)
    private suspend fun record(onChunk: (AudioChunk) -> Unit, onProblem: (String) -> Unit) {
        while (true) {
            try {
                recorder.chunks().collect { onChunk(it) }
            } catch (e: CancellationException) {
                throw e // stopping or pausing; this is not a microphone problem
            } catch (e: Exception) {
                Log.w(TAG, "Microphone problem, trying again", e)
                onProblem(e.message ?: "unknown problem")
                delay(RETRY_DELAY_MS)
            }
        }
    }

    /** For the heartbeat. "Charging" means plugged in, also when the battery is full. */
    private fun readBattery(): BatteryReading {
        // A null receiver just reads the last battery broadcast; nothing stays registered.
        val battery = registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED))
        val level = battery?.getIntExtra(BatteryManager.EXTRA_LEVEL, -1) ?: -1
        val scale = battery?.getIntExtra(BatteryManager.EXTRA_SCALE, -1) ?: -1
        val plugged = battery?.getIntExtra(BatteryManager.EXTRA_PLUGGED, 0) ?: 0
        val percent = if (level >= 0 && scale > 0) level * 100 / scale else 0
        return BatteryReading(percent.coerceIn(0, 100), charging = plugged != 0)
    }

    // The microphone type is from Android 11. ServiceCompat leaves it out on Android 8 and 9, and
    // Android 10 accepts it because the manifest declares the same type, so it is safe everywhere.
    @SuppressLint("InlinedApi")
    private fun goForeground(room: Room): Boolean = try {
        ServiceCompat.startForeground(
            this,
            NOTIFICATION_ID,
            notification(room, paused = false),
            ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE,
        )
        true
    } catch (e: RuntimeException) {
        // SecurityException without the microphone permission (Android 14+), or
        // ForegroundServiceStartNotAllowedException when the app is not on screen (Android 12+).
        Log.w(TAG, "Could not start in the foreground", e)
        false
    }

    /** Stops the service; onDestroy then shows [problem] on the screen. */
    private fun stopWith(problem: String) {
        Log.w(TAG, "Stopping: $problem")
        stopProblem = problem
        stopSelf()
    }

    private fun hasMicPermission(): Boolean =
        ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) ==
            PackageManager.PERMISSION_GRANTED

    /** Updates the notification, so it says "Paused" while the microphone is off. */
    private fun showNotification(room: Room, paused: Boolean) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) !=
            PackageManager.PERMISSION_GRANTED
        ) {
            return // the person said no to notifications; the service runs anyway
        }
        getSystemService(NotificationManager::class.java)
            .notify(NOTIFICATION_ID, notification(room, paused))
    }

    private fun notification(room: Room, paused: Boolean): Notification {
        val channel = NotificationChannel(
            CHANNEL_ID,
            getString(R.string.listening_channel_name),
            NotificationManager.IMPORTANCE_LOW, // no sound, no pop-up
        ).apply {
            description = getString(R.string.listening_channel_description)
            setShowBadge(false)
        }
        getSystemService(NotificationManager::class.java).createNotificationChannel(channel)

        // Tapping the notification opens the app, like tapping its icon.
        val openApp = Intent(this, MainActivity::class.java)
            .setAction(Intent.ACTION_MAIN)
            .addCategory(Intent.CATEGORY_LAUNCHER)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_RESET_TASK_IF_NEEDED)

        val title = if (paused) R.string.paused_notification_title else R.string.listening_notification_title
        val text = if (paused) R.string.paused_notification_text else R.string.listening_notification_text
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_listening)
            .setContentTitle(getString(title, room.label))
            .setContentText(getString(text))
            .setContentIntent(
                PendingIntent.getActivity(this, 0, openApp, PendingIntent.FLAG_IMMUTABLE),
            )
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setCategory(NotificationCompat.CATEGORY_SERVICE)
            // Show it at once; Android 12+ may otherwise wait up to 10 s.
            .setForegroundServiceBehavior(NotificationCompat.FOREGROUND_SERVICE_IMMEDIATE)
            .build()
    }

    // Held for exactly as long as the service listens and released in onDestroy, so no timeout.
    @SuppressLint("WakelockTimeout")
    private fun holdLocks() {
        if (wakeLock == null) {
            wakeLock = getSystemService(PowerManager::class.java)
                ?.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, LOCK_TAG)
                ?.apply {
                    setReferenceCounted(false)
                    acquire()
                }
        }
        if (wifiLock == null) {
            wifiLock = applicationContext.getSystemService(WifiManager::class.java)
                ?.createWifiLock(wifiLockMode(), LOCK_TAG)
                ?.apply {
                    setReferenceCounted(false)
                    acquire()
                }
        }
    }

    private fun releaseLocks() {
        wakeLock?.let { if (it.isHeld) it.release() }
        wakeLock = null
        wifiLock?.let { if (it.isHeld) it.release() }
        wifiLock = null
    }

    /** Low-latency Wi-Fi on Android 10+, as the contract asks; the older high-performance mode before. */
    @Suppress("DEPRECATION")
    private fun wifiLockMode(): Int =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            WifiManager.WIFI_MODE_FULL_LOW_LATENCY
        } else {
            WifiManager.WIFI_MODE_FULL_HIGH_PERF
        }

    companion object {
        private const val TAG = "ListenerService"
        private const val CHANNEL_ID = "listening"
        private const val NOTIFICATION_ID = 1
        private const val LOCK_TAG = "NonnaWatch:listening"
        private const val RETRY_DELAY_MS = 3_000L

        /** One client for the whole app: each OkHttp client has its own threads. */
        private val httpClient by lazy { hubHttpClient() }

        /**
         * Starts listening with the saved settings. Call only while the app is on screen: Android
         * gives the microphone only to a visible app.
         */
        fun start(context: Context) {
            val intent = Intent(context, ListenerService::class.java)
            try {
                ContextCompat.startForegroundService(context, intent)
            } catch (e: IllegalStateException) {
                // ForegroundServiceStartNotAllowedException: the app was not on screen.
                Log.w(TAG, "Could not start the service", e)
                ServiceStateHolder.set(ServiceState.Stopped("Android did not let the listener start"))
            }
        }

        // stopService, not a "stop" command sent through startForegroundService: that would make
        // the service call startForeground once more just to stop.
        fun stop(context: Context) {
            context.stopService(Intent(context, ListenerService::class.java))
        }
    }
}
