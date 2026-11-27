package app.nonnawatch.listener.hub

import app.nonnawatch.core.Room
import app.nonnawatch.core.protocol.heartbeatMessage
import app.nonnawatch.core.protocol.helloMessage
import app.nonnawatch.listener.audio.AudioChunk
import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlinx.coroutines.Deferred
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.async
import kotlinx.coroutines.channels.SendChannel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The protocol rules from docs/api-contract.md, against a fake hub. Time is simulated, so the
 * 10 s, 30 s and backoff waits take no real time.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class HubLinkTest {

    /** One connection; the test plays the hub through [hub] and reads what the phone sent. */
    private class FakeSocket(
        val url: String,
        val token: String,
        private val events: SendChannel<SocketEvent>,
    ) : HubSocket {
        val texts = mutableListOf<String>()
        val frames = mutableListOf<ByteArray>()
        var queued = 0L
        var closedWith: Int? = null
        var cancelled = false

        val heartbeats get() = texts.filter { it.startsWith("""{"type":"heartbeat"""") }

        override fun sendText(text: String): Boolean {
            texts += text
            return true
        }

        override fun sendBinary(bytes: ByteArray): Boolean {
            frames += bytes
            return true
        }

        override fun queuedBytes() = queued

        override fun close(code: Int, reason: String) {
            closedWith = code
        }

        override fun cancel() {
            cancelled = true
        }

        fun hub(event: SocketEvent) {
            events.trySend(event)
        }

        fun hubSays(json: String) = hub(SocketEvent.Text(json))

        fun welcome(paused: Boolean = false) = hubSays(
            """{"type": "welcome", "protocol": 1, "hub_id": "test-hub", "hub_time_ms": 1, "paused": $paused}""",
        )
    }

    private class FakeSockets : HubSocketFactory {
        val opened = mutableListOf<FakeSocket>()
        val last get() = opened.last()

        override fun open(url: String, token: String, events: SendChannel<SocketEvent>): HubSocket =
            FakeSocket(url, token, events).also { opened += it }
    }

    private val sockets = FakeSockets()
    private val paused = MutableStateFlow(false)
    private val config = HubConfig(
        url = "ws://10.0.2.2:8000/ws/listener",
        token = "secret",
        room = Room.KITCHEN,
        deviceId = "1f0c6c1e-4b7a-4d0e-9a51-7c2f0d3e8b11",
        appVersion = "0.1.0",
        deviceModel = "Nothing A001",
    )
    private val link = HubLink(
        config = config,
        sockets = sockets,
        paused = paused,
        battery = { BatteryReading(percent = 87, charging = true) },
        clock = { NOW },
        jitter = { 1.0 },
    )

    private fun chunk() = AudioChunk(captureMs = NOW - 1_000, samples = ShortArray(16_000))

    private fun seqOf(frame: ByteArray) = ByteBuffer.wrap(frame).order(ByteOrder.LITTLE_ENDIAN).getInt(8)

    private fun heartbeat(paused: Boolean) =
        heartbeatMessage(tsMs = NOW, batteryPct = 87, charging = true, paused = paused)

    /** Runs the link as the service does; the result is why it gave up, if it does. */
    private fun TestScope.startLink(): Deferred<String> = backgroundScope.async { link.run() }

    private fun TestScope.connect() {
        startLink()
        runCurrent()
        sockets.last.welcome()
        runCurrent()
    }

    @Test
    fun itConnectsWithTheTokenAndSaysHelloFirst() = runTest {
        startLink()
        runCurrent()

        val socket = sockets.opened.single()
        assertEquals("ws://10.0.2.2:8000/ws/listener", socket.url)
        assertEquals("secret", socket.token)
        assertEquals(
            listOf(helloMessage(config.deviceId, Room.KITCHEN, "0.1.0", "Nothing A001")),
            socket.texts,
        )
        assertEquals(LinkState.Connecting, link.state.value)
    }

    @Test
    fun afterTheWelcomeItSendsAHeartbeatAndTheAudio() = runTest {
        connect()
        val socket = sockets.last
        assertEquals(LinkState.Connected("test-hub", secondsSent = 0), link.state.value)
        assertEquals(listOf(heartbeat(paused = false)), socket.heartbeats)

        repeat(3) { link.send(chunk()) }

        assertEquals(listOf(0, 1, 2), socket.frames.map(::seqOf))
        assertTrue(socket.frames.all { it.size == 32_012 })
        assertEquals(LinkState.Connected("test-hub", secondsSent = 3), link.state.value)
    }

    @Test
    fun audioBeforeTheWelcomeIsDropped() = runTest {
        startLink()
        runCurrent()
        link.send(chunk())

        sockets.last.welcome()
        runCurrent()
        link.send(chunk())

        assertEquals(listOf(0), sockets.last.frames.map(::seqOf))
    }

    @Test
    fun aHeartbeatGoesEveryThirtySeconds() = runTest {
        connect()

        advanceTimeBy(30_000)
        runCurrent()
        assertEquals(2, sockets.last.heartbeats.size)

        advanceTimeBy(30_000)
        runCurrent()
        assertEquals(3, sockets.last.heartbeats.size)
    }

    @Test
    fun aWrongTokenStopsForGood() = runTest {
        val reason = startLink()
        runCurrent()

        sockets.last.hub(SocketEvent.Failed(httpCode = 403, message = "Expected HTTP 101 response but was '403 Forbidden'"))
        runCurrent()

        assertEquals("the hub refused the token", reason.await())
        advanceTimeBy(120_000)
        runCurrent()
        assertEquals(1, sockets.opened.size)
    }

    @Test
    fun anotherPhoneTakingOverTheRoomStopsForGood() = runTest {
        val reason = startLink()
        runCurrent()
        sockets.last.welcome()
        runCurrent()

        sockets.last.hub(SocketEvent.Closed(code = 4409, reason = "replaced"))
        runCurrent()

        assertEquals("another phone took over this room", reason.await())
        assertEquals(1, sockets.opened.size)
    }

    @Test
    fun aBadHelloStopsForGoodAndSaysWhy() = runTest {
        val reason = startLink()
        runCurrent()

        sockets.last.hub(SocketEvent.Closed(code = 4400, reason = "unknown room"))
        runCurrent()

        assertEquals("the hub refused this phone (unknown room)", reason.await())
    }

    @Test
    fun withoutAWelcomeWithinTenSecondsItTriesAgain() = runTest {
        startLink()
        runCurrent()
        val first = sockets.last

        advanceTimeBy(9_999)
        runCurrent()
        assertEquals(LinkState.Connecting, link.state.value)

        advanceTimeBy(1)
        runCurrent()
        assertTrue(first.cancelled)
        assertEquals(
            LinkState.Waiting("no welcome from the hub within 10 s", retryInSeconds = 1),
            link.state.value,
        )

        advanceTimeBy(1_000)
        runCurrent()
        assertEquals(2, sockets.opened.size)
    }

    @Test
    fun theWaitsGrowAndStopGrowingAtThirtySeconds() = runTest {
        startLink()
        val waits = mutableListOf<Int>()

        repeat(7) {
            runCurrent()
            sockets.last.hub(SocketEvent.Failed(httpCode = null, message = "Connection refused"))
            runCurrent()
            val waiting = link.state.value as LinkState.Waiting
            assertEquals("hub not reachable", waiting.reason)
            waits += waiting.retryInSeconds
            advanceTimeBy(waiting.retryInSeconds * 1_000L)
        }

        assertEquals(listOf(1, 2, 4, 8, 16, 30, 30), waits)
        runCurrent()
        assertEquals(8, sockets.opened.size)
    }

    @Test
    fun theWaitsStartOverAfterAWelcome() = runTest {
        startLink()
        repeat(2) { // two failures: waits of 1 s and 2 s
            runCurrent()
            sockets.last.hub(SocketEvent.Failed(httpCode = null, message = "Connection refused"))
            runCurrent()
            advanceTimeBy((link.state.value as LinkState.Waiting).retryInSeconds * 1_000L)
        }
        runCurrent()
        sockets.last.welcome()
        runCurrent()

        sockets.last.hub(SocketEvent.Closed(code = 1001, reason = "hub shutting down"))
        runCurrent()

        assertEquals(
            LinkState.Waiting("the hub closed the connection", retryInSeconds = 1),
            link.state.value,
        )
    }

    @Test
    fun seqStartsAtZeroOnEveryConnection() = runTest {
        connect()
        link.send(chunk())
        link.send(chunk())

        sockets.last.hub(SocketEvent.Failed(httpCode = null, message = "Software caused connection abort"))
        runCurrent()
        link.send(chunk()) // disconnected: dropped, not kept for later
        advanceTimeBy(1_000)
        runCurrent()
        sockets.last.welcome()
        runCurrent()
        link.send(chunk())

        assertEquals(listOf(0, 1), sockets.opened[0].frames.map(::seqOf))
        assertEquals(listOf(0), sockets.opened[1].frames.map(::seqOf))
    }

    @Test
    fun theHubCanPauseAndResumeThePhone() = runTest {
        connect()
        val socket = sockets.last

        socket.hubSays("""{"type": "set_paused", "paused": true}""")
        runCurrent()
        assertTrue(paused.value)
        assertEquals(heartbeat(paused = true), socket.heartbeats.last())

        socket.hubSays("""{"type": "set_paused", "paused": false}""")
        runCurrent()
        assertFalse(paused.value)
        assertEquals(heartbeat(paused = false), socket.heartbeats.last())
    }

    @Test
    fun aPauseOnThePhoneIsToldToTheHubAtOnce() = runTest {
        connect()

        paused.value = true
        runCurrent()

        assertEquals(listOf(heartbeat(paused = false), heartbeat(paused = true)), sockets.last.heartbeats)
    }

    @Test
    fun aWelcomeThatSaysPausedPausesThePhone() = runTest {
        startLink()
        runCurrent()

        sockets.last.welcome(paused = true)
        runCurrent()

        assertTrue(paused.value)
        assertEquals(listOf(heartbeat(paused = true)), sockets.last.heartbeats)
    }

    @Test
    fun aWelcomeNeverUndoesAPauseChosenOnThePhone() = runTest {
        paused.value = true
        startLink()
        runCurrent()

        sockets.last.welcome(paused = false)
        runCurrent()

        assertTrue(paused.value)
        assertEquals(listOf(heartbeat(paused = true)), sockets.last.heartbeats)
    }

    @Test
    fun withTenSecondsOfAudioWaitingASecondIsSkippedButCounted() = runTest {
        connect()
        val socket = sockets.last

        link.send(chunk())
        socket.queued = 320_001
        link.send(chunk())
        socket.queued = 0
        link.send(chunk())

        assertEquals(listOf(0, 2), socket.frames.map(::seqOf))
    }

    @Test
    fun stoppingSaysGoodbyeWithANormalClose() = runTest {
        val run = startLink()
        runCurrent()
        sockets.last.welcome()
        runCurrent()

        run.cancel()
        runCurrent()

        assertEquals(1000, sockets.last.closedWith)
        assertFalse(sockets.last.cancelled)
    }

    @Test
    fun messagesThePhoneDoesNotActOnAreIgnored() = runTest {
        connect()
        val socket = sockets.last

        socket.hubSays("""{"type": "ask", "ask_id": "kitchen-1", "reason": "thud", "text": "Stai bene?", "lang": "it-IT"}""")
        socket.hubSays("""{"type": "checkin_clip", "clip_id": null}""")
        socket.hubSays("""{"type": "error", "code": "bad_frame", "message": "frame must be 32012 bytes, got 32010"}""")
        socket.hubSays("""{"type": "something_new"}""")
        socket.hubSays("not json")
        runCurrent()

        assertEquals(LinkState.Connected("test-hub", secondsSent = 0), link.state.value)
        assertEquals(1, sockets.opened.size)
    }

    @Test
    fun aWrongPageOnTheHubSaysCheckTheAddress() = runTest {
        startLink()
        runCurrent()

        sockets.last.hub(SocketEvent.Failed(httpCode = 404, message = "Expected HTTP 101 response but was '404 Not Found'"))
        runCurrent()

        assertEquals(
            LinkState.Waiting("the hub answered HTTP 404; check the address", retryInSeconds = 1),
            link.state.value,
        )
    }

    private companion object {
        const val NOW = 1_795_698_222_000L
    }
}
