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
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.net.wifi.WifiManager
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import android.util.Log
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat
import app.nonnawatch.core.Room
import app.nonnawatch.listener.audio.MicRecorder
import app.nonnawatch.listener.audio.peakPercent
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

/**
 * Keeps the microphone on, also with the screen off and the app closed.
 *
 * A normal app is frozen soon after it leaves the screen. A foreground service keeps running, and
 * Android makes it show a notification so the person always knows the microphone is on. It is
 * declared with type "microphone" in the manifest, which Android 14+ requires.
 *
 * While it runs it holds a partial WakeLock (the processor stays awake with the screen off) and a
 * WifiLock (Wi-Fi does not go to sleep), as docs/api-contract.md asks.
 *
 * A2 only records and counts the audio; A3 sends each chunk to the hub.
 */
class ListenerService : Service() {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private val recorder = MicRecorder()
    private var listening: Job? = null
    private var wakeLock: PowerManager.WakeLock? = null
    private var wifiLock: WifiManager.WifiLock? = null

    /** Why the service stopped by itself; shown on the screen. Null when the user tapped Stop. */
    private var stopProblem: String? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val room = intent?.getStringExtra(EXTRA_ROOM)?.let(Room::fromId)

        // A service started with startForegroundService must call startForeground within seconds,
        // even if it then stops, or Android ends the app. So this comes before any other check.
        if (!goForeground(room)) {
            stopWith("Android did not let the listener start")
            return START_NOT_STICKY
        }
        if (room == null) {
            stopWith("no room was chosen")
            return START_NOT_STICKY
        }
        if (!hasMicPermission()) {
            stopWith("the microphone permission is missing")
            return START_NOT_STICKY
        }
        if (listening?.isActive != true) startListening(room)

        // Not sticky: if Android kills the service, it does not restart it by itself. A restarted
        // service starts in the background, where Android gives it no microphone. Someone opens
        // the app and taps Start again (docs/api-contract.md, notes for the listener app).
        return START_NOT_STICKY
    }

    override fun onDestroy() {
        scope.cancel() // stops collecting, so MicRecorder releases the microphone
        releaseLocks()
        ServiceStateHolder.set(ServiceState.Stopped(stopProblem))
        super.onDestroy()
    }

    // onStartCommand checks the permission before calling this.
    @SuppressLint("MissingPermission")
    private fun startListening(room: Room) {
        holdLocks()
        ServiceStateHolder.set(ServiceState.Listening(room, secondsRecorded = 0, levelPercent = 0))
        listening = scope.launch {
            var seconds = 0L
            while (isActive) {
                try {
                    recorder.chunks().collect { chunk ->
                        seconds += 1
                        // The chunk is dropped after this; A3 sends it to the hub here instead.
                        ServiceStateHolder.set(
                            ServiceState.Listening(room, seconds, chunk.peakPercent()),
                        )
                    }
                } catch (e: CancellationException) {
                    throw e // the service is stopping; this is not a microphone problem
                } catch (e: Exception) {
                    Log.w(TAG, "Microphone problem, trying again", e)
                    ServiceStateHolder.set(
                        ServiceState.MicProblem(room, e.message ?: "unknown problem"),
                    )
                    delay(RETRY_DELAY_MS)
                }
            }
        }
    }

    // The microphone type is from Android 11. ServiceCompat leaves it out on Android 8 and 9, and
    // Android 10 accepts it because the manifest declares the same type, so it is safe everywhere.
    @SuppressLint("InlinedApi")
    private fun goForeground(room: Room?): Boolean = try {
        ServiceCompat.startForeground(
            this,
            NOTIFICATION_ID,
            notification(room),
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

    private fun notification(room: Room?): Notification {
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

        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_listening)
            .setContentTitle(getString(R.string.listening_notification_title, room?.label ?: "…"))
            .setContentText(getString(R.string.listening_notification_text))
            .setContentIntent(
                PendingIntent.getActivity(this, 0, openApp, PendingIntent.FLAG_IMMUTABLE),
            )
            .setOngoing(true)
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
        private const val EXTRA_ROOM = "room"
        private const val CHANNEL_ID = "listening"
        private const val NOTIFICATION_ID = 1
        private const val LOCK_TAG = "NonnaWatch:listening"
        private const val RETRY_DELAY_MS = 3_000L

        /** Call only while the app is on screen: Android gives the microphone only to a visible app. */
        fun start(context: Context, room: Room) {
            val intent = Intent(context, ListenerService::class.java).putExtra(EXTRA_ROOM, room.id)
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
