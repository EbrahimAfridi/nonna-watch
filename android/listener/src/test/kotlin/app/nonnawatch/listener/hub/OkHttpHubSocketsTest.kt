package app.nonnawatch.listener.hub

import app.nonnawatch.core.protocol.CloseCodes
import app.nonnawatch.core.protocol.FRAME_BYTES
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** The real OkHttp connection, against a small fake hub on this PC (MockWebServer). */
class OkHttpHubSocketsTest {
    private val server = MockWebServer()
    private val client = hubHttpClient()
    private val events = Channel<SocketEvent>(Channel.UNLIMITED)

    @After
    fun tearDown() {
        server.close()
        client.dispatcher.executorService.shutdown()
        client.connectionPool.evictAll()
    }

    private fun hubUrl() = server.url("/ws/listener").toString().replaceFirst("http://", "ws://")

    private suspend fun nextEvent() = withTimeout(15_000) { events.receive() }

    @Test
    fun theTokenGoesInAHeaderAndMessagesTravelBothWays(): Unit = runBlocking {
        val heardByHub = LinkedBlockingQueue<Any>()
        server.enqueue(
            MockResponse.Builder().webSocketUpgrade(
                object : WebSocketListener() {
                    override fun onOpen(webSocket: WebSocket, response: Response) {
                        webSocket.send("""{"type":"welcome","protocol":1,"hub_id":"mock","hub_time_ms":1,"paused":false}""")
                    }

                    override fun onMessage(webSocket: WebSocket, text: String) {
                        heardByHub.put(text)
                    }

                    override fun onMessage(webSocket: WebSocket, bytes: ByteString) {
                        heardByHub.put(bytes)
                    }
                },
            ).build(),
        )
        server.start()

        val socket = OkHttpHubSockets(client).open(hubUrl(), "secret", events)
        socket.sendText("hello")
        socket.sendBinary(ByteArray(FRAME_BYTES))

        val request = server.takeRequest(15, TimeUnit.SECONDS)
        assertEquals("Bearer secret", request?.headers?.get("Authorization"))
        assertEquals("/ws/listener", request?.url?.encodedPath)
        assertEquals(SocketEvent.Opened, nextEvent())
        assertTrue((nextEvent() as SocketEvent.Text).text.contains(""""type":"welcome""""))
        assertEquals("hello", heardByHub.poll(15, TimeUnit.SECONDS))
        assertEquals(FRAME_BYTES, (heardByHub.poll(15, TimeUnit.SECONDS) as ByteString).size)

        socket.close(CloseCodes.NORMAL, "test over")
    }

    @Test
    fun aRefusedUpgradeReportsTheHttpCode(): Unit = runBlocking {
        server.enqueue(MockResponse.Builder().code(403).build())
        server.start()

        OkHttpHubSockets(client).open(hubUrl(), "wrong", events)

        assertEquals(403, (nextEvent() as SocketEvent.Failed).httpCode)
    }

    @Test
    fun noHubAtAllIsAFailureWithoutAnHttpCode(): Unit = runBlocking {
        server.start()
        val nobodyListens = hubUrl()
        server.close() // the port is free again, so nothing answers there

        OkHttpHubSockets(client).open(nobodyListens, "secret", events)

        assertNull((nextEvent() as SocketEvent.Failed).httpCode)
    }

    @Test
    fun anAddressOkHttpCannotReadIsAFailure(): Unit = runBlocking {
        OkHttpHubSockets(client).open("ws://", "secret", events)

        assertEquals(SocketEvent.Failed(httpCode = null, message = "not a valid hub address"), nextEvent())
    }
}
