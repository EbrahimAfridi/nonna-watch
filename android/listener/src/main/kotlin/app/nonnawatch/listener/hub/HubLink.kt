package app.nonnawatch.listener.hub

import app.nonnawatch.core.Room
import app.nonnawatch.core.protocol.CloseCodes
import app.nonnawatch.core.protocol.HubMessage
import app.nonnawatch.core.protocol.askNotPlayedMessage
import app.nonnawatch.core.protocol.askPlayedMessage
import app.nonnawatch.core.protocol.audioFrame
import app.nonnawatch.core.protocol.heartbeatMessage
import app.nonnawatch.core.protocol.helloMessage
import app.nonnawatch.core.protocol.lightMessage
import app.nonnawatch.core.protocol.parseHubMessage
import app.nonnawatch.listener.audio.AudioChunk
import app.nonnawatch.listener.light.LightChange
import app.nonnawatch.listener.voice.AskResult
import app.nonnawatch.listener.voice.NotPlayedReason
import app.nonnawatch.listener.voice.VoiceCheck
import kotlin.math.roundToLong
import kotlin.random.Random
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.cancelChildren
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.channels.ReceiveChannel
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.drop
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull

/** Everything the phone needs to reach the hub and introduce itself in `hello`. */
data class HubConfig(
    val url: String,
    val token: String,
    val room: Room,
    val deviceId: String,
    val appVersion: String,
    val deviceModel: String,
)

/** The link to the hub, as the screen shows it. */
sealed interface LinkState {
    data object Connecting : LinkState

    data class Connected(val hubId: String, val secondsSent: Long) : LinkState

    /** Not connected; the next try is in [retryInSeconds]. */
    data class Waiting(val reason: String, val retryInSeconds: Int) : LinkState
}

data class BatteryReading(val percent: Int, val charging: Boolean)

/**
 * Keeps this phone connected to the hub, as docs/api-contract.md describes: hello, wait for
 * welcome, then audio frames and heartbeats; reconnect with backoff when the link drops; give up
 * only when the hub refuses this phone for good.
 *
 * [paused] is the pause switch shared with the service: the hub flips it with `welcome` and
 * `set_paused`, the Pause button flips it on the phone, and every change sends a heartbeat at once.
 *
 * [voiceCheck] plays the check-in question when the hub sends `ask`, and keeps the family's
 * recording from `checkin_clip`. Audio and heartbeats keep going while the question plays.
 *
 * Call [send] and [sendLight] from the thread that runs [run] (the service uses the main thread
 * for all three).
 */
class HubLink(
    private val config: HubConfig,
    private val sockets: HubSocketFactory,
    private val paused: MutableStateFlow<Boolean>,
    private val battery: () -> BatteryReading,
    private val voiceCheck: VoiceCheck,
    private val clock: () -> Long = System::currentTimeMillis,
    private val jitter: () -> Double = ::randomJitter,
    private val log: (String) -> Unit = {},
) {
    private val _state = MutableStateFlow<LinkState>(LinkState.Connecting)
    val state: StateFlow<LinkState> = _state.asStateFlow()

    /** Set while the hub has welcomed this phone; audio and heartbeats go through it. */
    private var session: Session? = null

    /**
     * Stays connected until the hub refuses this phone for good, then returns why (wrong token,
     * another phone took over the room, bad hello). Cancel the coroutine to stop listening; the
     * hub then gets a normal close.
     */
    suspend fun run(): String {
        var failures = 0
        while (true) {
            _state.value = LinkState.Connecting
            when (val end = connectOnce()) {
                is SessionEnd.GiveUp -> return end.reason
                is SessionEnd.Retry -> {
                    if (end.welcomed) failures = 0 // the contract: reset the backoff after a welcome
                    log("Not connected: ${end.reason}")
                    waitBeforeRetry(end.reason, backoffMs(failures, jitter()))
                    failures += 1
                }
            }
        }
    }

    /**
     * Sends one second of audio if the hub has welcomed this phone. Otherwise the audio is
     * dropped: the contract says to keep none while disconnected.
     */
    fun send(chunk: AudioChunk) {
        session?.sendAudio(chunk)
    }

    /**
     * Tells the hub the room went dark or bright, if the hub has welcomed this phone. Until A5
     * keeps them for later, a change while disconnected is dropped.
     */
    fun sendLight(change: LightChange) {
        val current = session
        if (current == null) {
            log("Light ${change.state.wire}, not sent: not connected to the hub")
            return
        }
        current.sendLight(change)
    }

    private suspend fun connectOnce(): SessionEnd {
        val events = Channel<SocketEvent>(Channel.UNLIMITED)
        val socket = sockets.open(config.url, config.token, events)
        var stoppedByUs = false
        try {
            // OkHttp keeps the hello until the connection is open, so it can be sent right away.
            socket.sendText(
                helloMessage(config.deviceId, config.room, config.appVersion, config.deviceModel),
            )
            val welcome = when (val opening = withTimeoutOrNull(WELCOME_TIMEOUT_MS) { awaitWelcome(events) }) {
                null -> return SessionEnd.Retry("no welcome from the hub within 10 s", welcomed = false)
                is Opening.Ended -> return opening.end
                is Opening.Welcomed -> opening.welcome
            }
            return stayConnected(socket, events, welcome)
        } catch (e: CancellationException) {
            stoppedByUs = true
            throw e
        } finally {
            session = null
            if (stoppedByUs) socket.close(CloseCodes.NORMAL, "listening stopped") else socket.cancel()
        }
    }

    private suspend fun awaitWelcome(events: ReceiveChannel<SocketEvent>): Opening {
        for (event in events) {
            when (event) {
                SocketEvent.Opened -> log("Connected, waiting for welcome")
                is SocketEvent.Text -> when (val message = parseHubMessage(event.text)) {
                    is HubMessage.Welcome -> return Opening.Welcomed(message)
                    is HubMessage.Error -> log("Hub error ${message.code}: ${message.message}")
                    else -> Unit
                }
                is SocketEvent.Closed -> return Opening.Ended(endFor(event, welcomed = false))
                is SocketEvent.Failed -> return Opening.Ended(endFor(event, welcomed = false))
            }
        }
        return Opening.Ended(SessionEnd.Retry("connection lost", welcomed = false))
    }

    private suspend fun stayConnected(
        socket: HubSocket,
        events: ReceiveChannel<SocketEvent>,
        welcome: HubMessage.Welcome,
    ): SessionEnd = coroutineScope {
        // The family may have paused while the phone was offline, so apply it at once. A welcome
        // never un-pauses: a pause the person chose on this phone must survive a reconnect.
        if (welcome.paused) paused.value = true

        val current = Session(socket, welcome.hubId, questions = this)
        session = current
        _state.value = LinkState.Connected(welcome.hubId, secondsSent = 0)
        log("Welcomed by hub ${welcome.hubId}")

        launch {
            launch { paused.drop(1).collect { current.sendHeartbeat() } } // at once on every change
            while (true) {
                current.sendHeartbeat()
                delay(HEARTBEAT_MS)
            }
        }
        val end = readUntilEnd(events, current)
        // Stops the heartbeats, and a question still playing: the hub cannot hear the answer over
        // a lost connection, and alerts the family by itself when no ask_played comes.
        coroutineContext.cancelChildren()
        end
    }

    private suspend fun readUntilEnd(events: ReceiveChannel<SocketEvent>, current: Session): SessionEnd {
        for (event in events) {
            when (event) {
                SocketEvent.Opened -> Unit
                is SocketEvent.Text -> when (val message = parseHubMessage(event.text)) {
                    is HubMessage.SetPaused -> paused.value = message.paused
                    is HubMessage.Error -> log("Hub error ${message.code}: ${message.message}")
                    is HubMessage.Ask -> current.ask(message)
                    // Saved before the next message is read, so an ask right after it plays the new one.
                    is HubMessage.CheckinClip -> voiceCheck.saveClip(message.audio)
                    HubMessage.CheckinClipDeleted -> voiceCheck.deleteClip()
                    // Unknown types are ignored, as the contract says.
                    is HubMessage.Welcome, null -> Unit
                }
                is SocketEvent.Closed -> return endFor(event, welcomed = true)
                is SocketEvent.Failed -> return endFor(event, welcomed = true)
            }
        }
        return SessionEnd.Retry("connection lost", welcomed = true)
    }

    private suspend fun waitBeforeRetry(reason: String, waitMs: Long) {
        var left = waitMs
        while (left > 0) {
            _state.value = LinkState.Waiting(reason, retryInSeconds = ((left + 999) / 1000).toInt())
            val step = minOf(left, 1_000L)
            delay(step)
            left -= step
        }
    }

    /** One welcomed connection. [questions] runs the check-in questions; it ends with the connection. */
    private inner class Session(
        private val socket: HubSocket,
        private val hubId: String,
        private val questions: CoroutineScope,
    ) {
        private var seq = 0 // restarts at 0 on every connection
        private var secondsSent = 0L
        private var asking: Job? = null

        /** Plays the question without holding up the audio, then tells the hub how it went. */
        fun ask(ask: HubMessage.Ask) {
            if (asking?.isActive == true) {
                log("The hub asked again while a question was still playing")
                socket.sendText(askNotPlayedMessage(ask.askId, NotPlayedReason.BUSY))
                return
            }
            log("The hub asks (${ask.reason.ifBlank { "no reason given" }}): ${ask.text}")
            asking = questions.launch {
                val result = voiceCheck.ask(ask.text, ask.lang)
                val answer = when (result) {
                    is AskResult.Played -> askPlayedMessage(ask.askId, result.startedMs, result.endedMs)
                    is AskResult.NotPlayed -> askNotPlayedMessage(ask.askId, result.reason)
                }
                log("Check-in question: $result")
                socket.sendText(answer)
            }
        }

        fun sendAudio(chunk: AudioChunk) {
            val frameSeq = seq++
            // Real time beats completeness: with 10 s of audio already waiting, skip this second.
            // seq still moves on, so the hub sees the gap.
            if (socket.queuedBytes() > MAX_QUEUED_BYTES) return
            if (socket.sendBinary(audioFrame(chunk.captureMs, frameSeq, chunk.samples))) {
                secondsSent += 1
                _state.value = LinkState.Connected(hubId, secondsSent)
            }
        }

        fun sendHeartbeat() {
            val reading = battery()
            socket.sendText(heartbeatMessage(clock(), reading.percent, reading.charging, paused.value))
        }

        fun sendLight(change: LightChange) {
            log("Light ${change.state.wire} (${change.lux} lux)")
            socket.sendText(lightMessage(change.tsMs, change.state, change.lux))
        }
    }

    private sealed interface Opening {
        data class Welcomed(val welcome: HubMessage.Welcome) : Opening

        data class Ended(val end: SessionEnd) : Opening
    }
}

/** How a connection ended, and so what to do next. */
internal sealed interface SessionEnd {
    /** Try again after a wait. [welcomed]: the hub had welcomed this phone, so the waits start over. */
    data class Retry(val reason: String, val welcomed: Boolean) : SessionEnd

    /** The hub refused this phone; trying again would not help. */
    data class GiveUp(val reason: String) : SessionEnd
}

/** What the contract's close-code table says to do after [event]. */
internal fun endFor(event: SocketEvent, welcomed: Boolean): SessionEnd = when (event) {
    is SocketEvent.Closed -> when (event.code) {
        CloseCodes.BAD_HELLO -> SessionEnd.GiveUp(
            "the hub refused this phone (${event.reason.ifBlank { "bad hello" }})",
        )
        CloseCodes.REPLACED -> SessionEnd.GiveUp("another phone took over this room")
        else -> SessionEnd.Retry("the hub closed the connection", welcomed)
    }
    is SocketEvent.Failed -> when (event.httpCode) {
        CloseCodes.HTTP_WRONG_TOKEN -> SessionEnd.GiveUp("the hub refused the token")
        null -> SessionEnd.Retry("hub not reachable", welcomed)
        else -> SessionEnd.Retry("the hub answered HTTP ${event.httpCode}; check the address", welcomed)
    }
    SocketEvent.Opened, is SocketEvent.Text -> SessionEnd.Retry("connection lost", welcomed)
}

/** The wait before the next try after [failures] failed tries in a row: 1, 2, 4, 8, 16, then 30 s, times [jitter]. */
internal fun backoffMs(failures: Int, jitter: Double): Long {
    val seconds = BACKOFF_SECONDS[failures.coerceIn(0, BACKOFF_SECONDS.lastIndex)]
    return (seconds * 1_000 * jitter).roundToLong()
}

/** ±20 %, so phones that lost the hub together do not all knock again at the same moment. */
internal fun randomJitter(): Double = 0.8 + Random.nextDouble() * 0.4

private val BACKOFF_SECONDS = listOf(1, 2, 4, 8, 16, 30)
private const val WELCOME_TIMEOUT_MS = 10_000L
private const val HEARTBEAT_MS = 30_000L

/** 10 s of audio. Above this the phone skips frames instead of queueing more. */
internal const val MAX_QUEUED_BYTES = 320_000L
