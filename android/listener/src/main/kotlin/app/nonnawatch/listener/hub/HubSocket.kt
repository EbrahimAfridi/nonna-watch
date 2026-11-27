package app.nonnawatch.listener.hub

import kotlinx.coroutines.channels.SendChannel

/**
 * What happened on a connection to the hub. OkHttp reports these on its own threads; they reach
 * [HubLink] through a channel, so all the protocol logic runs in one place, one event at a time.
 */
sealed interface SocketEvent {
    data object Opened : SocketEvent

    data class Text(val text: String) : SocketEvent

    /** The hub closed the connection with a WebSocket close [code] (see CloseCodes). */
    data class Closed(val code: Int, val reason: String) : SocketEvent

    /**
     * The connection failed: no network, the hub is not running, or the hub refused the upgrade
     * with [httpCode] (403 for a wrong token). [httpCode] is null when no answer came at all.
     */
    data class Failed(val httpCode: Int?, val message: String) : SocketEvent
}

/** One connection to the hub, as [HubLink] uses it. */
interface HubSocket {
    fun sendText(text: String): Boolean

    fun sendBinary(bytes: ByteArray): Boolean

    /** Bytes waiting to go out. */
    fun queuedBytes(): Long

    /** Ends the connection politely; the hub sees [code]. */
    fun close(code: Int, reason: String)

    /** Drops the connection at once, without a goodbye. */
    fun cancel()
}

/** Opens connections to the hub. The real one is [OkHttpHubSockets]; tests use a fake. */
fun interface HubSocketFactory {
    /** Opens a connection; everything that happens on it is sent to [events]. Never blocks. */
    fun open(url: String, token: String, events: SendChannel<SocketEvent>): HubSocket
}
