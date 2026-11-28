package app.nonnawatch.listener.hub

import app.nonnawatch.core.protocol.CloseCodes
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.channels.SendChannel
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString.Companion.toByteString

/** The OkHttp client for the hub. Make one and share it: each client has its own threads. */
fun hubHttpClient(): OkHttpClient = OkHttpClient.Builder()
    .connectTimeout(10, TimeUnit.SECONDS)
    // The contract's keepalive: the hub answers pings, so a dead link is noticed within about 40 s.
    .pingInterval(20, TimeUnit.SECONDS)
    .build()

/** Real WebSocket connections to the hub, through OkHttp. */
class OkHttpHubSockets(private val client: OkHttpClient) : HubSocketFactory {

    override fun open(url: String, token: String, events: SendChannel<SocketEvent>): HubSocket {
        val request = try {
            Request.Builder()
                .url(url) // OkHttp accepts ws:// and wss:// here
                // The token goes in a header, never in the URL: Cloud Run logs request URLs.
                .header("Authorization", "Bearer $token")
                .build()
        } catch (e: IllegalArgumentException) {
            events.trySend(SocketEvent.Failed(httpCode = null, message = "not a valid hub address"))
            return NoSocket
        }
        return Socket(client.newWebSocket(request, Listener(events)))
    }

    private class Listener(private val events: SendChannel<SocketEvent>) : WebSocketListener() {
        override fun onOpen(webSocket: WebSocket, response: Response) {
            events.trySend(SocketEvent.Opened)
        }

        override fun onMessage(webSocket: WebSocket, text: String) {
            events.trySend(SocketEvent.Text(text))
        }

        override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
            webSocket.close(CloseCodes.NORMAL, null) // answer the hub's goodbye
            events.trySend(SocketEvent.Closed(code, reason))
        }

        override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
            events.trySend(SocketEvent.Closed(code, reason))
        }

        override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
            events.trySend(SocketEvent.Failed(response?.code, t.message ?: t.javaClass.simpleName))
        }
    }

    private class Socket(private val webSocket: WebSocket) : HubSocket {
        override fun sendText(text: String) = webSocket.send(text)

        override fun sendBinary(bytes: ByteArray) = webSocket.send(bytes.toByteString())

        override fun queuedBytes() = webSocket.queueSize()

        override fun close(code: Int, reason: String) {
            webSocket.close(code, reason)
        }

        override fun cancel() = webSocket.cancel()
    }

    /** Stands in when the address could not even be turned into a request. */
    private object NoSocket : HubSocket {
        override fun sendText(text: String) = false

        override fun sendBinary(bytes: ByteArray) = false

        override fun queuedBytes() = 0L

        override fun close(code: Int, reason: String) = Unit

        override fun cancel() = Unit
    }
}
