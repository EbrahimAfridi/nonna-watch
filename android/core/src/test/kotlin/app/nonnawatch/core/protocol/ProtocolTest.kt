package app.nonnawatch.core.protocol

import app.nonnawatch.core.Room
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Test

class ProtocolTest {

    @Test
    fun aFrameMatchesTheWorkedExampleInTheContract() {
        val samples = ShortArray(FRAME_SAMPLES).also {
            it[0] = 0
            it[1] = 1000
            it[2] = -1000
        }

        val frame = audioFrame(captureMs = 1_795_698_192_000L, seq = 42, samples = samples)

        assertEquals(32_012, frame.size)
        val expectedStart = listOf(
            0x80, 0xee, 0xf3, 0x17, 0xa2, 0x01, 0x00, 0x00, // capture_ms
            0x2a, 0x00, 0x00, 0x00, // seq
            0x00, 0x00, 0xe8, 0x03, 0x18, 0xfc, // pcm
        ).map { it.toByte() }.toByteArray()
        assertArrayEquals(expectedStart, frame.copyOfRange(0, expectedStart.size))
    }

    @Test
    fun aFrameMustBeExactlyOneSecond() {
        assertThrows(IllegalArgumentException::class.java) {
            audioFrame(captureMs = 0, seq = 0, samples = ShortArray(15_999))
        }
    }

    @Test
    fun helloHasEveryFieldTheHubChecks() {
        val hello = helloMessage(
            deviceId = "1f0c6c1e-4b7a-4d0e-9a51-7c2f0d3e8b11",
            room = Room.LIVING_ROOM,
            appVersion = "0.1.0",
            deviceModel = "Nothing A001",
        )

        assertEquals(
            """{"type":"hello","protocol":1,"device_id":"1f0c6c1e-4b7a-4d0e-9a51-7c2f0d3e8b11",""" +
                """"room":"living_room","sample_rate":16000,"app_version":"0.1.0",""" +
                """"device_model":"Nothing A001"}""",
            hello,
        )
    }

    @Test
    fun heartbeatMatchesTheContract() {
        assertEquals(
            """{"type":"heartbeat","ts_ms":1795698222000,"battery_pct":87,"charging":true,"paused":false}""",
            heartbeatMessage(tsMs = 1_795_698_222_000L, batteryPct = 87, charging = true, paused = false),
        )
    }

    @Test
    fun heartbeatBatteryStaysBetweenZeroAndOneHundred() {
        // The hub rejects a heartbeat outside 0..100.
        assertEquals(
            """{"type":"heartbeat","ts_ms":0,"battery_pct":100,"charging":false,"paused":true}""",
            heartbeatMessage(tsMs = 0, batteryPct = 140, charging = false, paused = true),
        )
    }

    @Test
    fun welcomeIsRead() {
        assertEquals(
            HubMessage.Welcome(hubId = "ebrahim-mac", hubTimeMs = 1_795_698_192_150L, paused = false),
            parseHubMessage(
                """{"type": "welcome", "protocol": 1, "hub_id": "ebrahim-mac", "hub_time_ms": 1795698192150, "paused": false}""",
            ),
        )
    }

    @Test
    fun setPausedAndErrorAreRead() {
        assertEquals(HubMessage.SetPaused(true), parseHubMessage("""{"type": "set_paused", "paused": true}"""))
        assertEquals(
            HubMessage.Error("bad_frame", "frame must be 32012 bytes, got 32010"),
            parseHubMessage("""{"type": "error", "code": "bad_frame", "message": "frame must be 32012 bytes, got 32010"}"""),
        )
    }

    @Test
    fun unknownFieldsAreIgnored() {
        assertEquals(
            HubMessage.SetPaused(false),
            parseHubMessage("""{"type": "set_paused", "paused": false, "by": "luca", "extra": {"x": 1}}"""),
        )
    }

    @Test
    fun messagesThePhoneDoesNotActOnGiveNull() {
        assertNull(parseHubMessage("""{"type": "something_new", "x": 1}"""))
        assertNull(parseHubMessage("""{"no_type": true}"""))
    }

    @Test
    fun askIsRead() {
        assertEquals(
            HubMessage.Ask(askId = "kitchen-1795698192000", reason = "thud", text = "Mamma, stai bene?", lang = "it-IT"),
            parseHubMessage(
                """{"type": "ask", "ask_id": "kitchen-1795698192000", "reason": "thud",""" +
                    """ "text": "Mamma, stai bene?", "lang": "it-IT"}""",
            ),
        )
    }

    @Test
    fun anAskThePhoneCouldNotAnswerOrSpeakGivesNull() {
        assertNull(parseHubMessage("""{"type": "ask", "text": "Stai bene?", "lang": "it-IT"}"""))
        assertNull(parseHubMessage("""{"type": "ask", "ask_id": "kitchen-1", "lang": "it-IT"}"""))
        assertNull(parseHubMessage("""{"type": "ask", "ask_id": "kitchen-1", "text": "Stai bene?"}"""))
    }

    @Test
    fun aCheckinClipArrivesAsBase64AndIsDecoded() {
        // "AAAAIGZ0eXBNNEEg" is the start of an .m4a file: 00 00 00 20 then "ftypM4A ".
        val clip = parseHubMessage(
            """{"type": "checkin_clip", "clip_id": "3", "mime": "audio/mp4", "data_b64": "AAAAIGZ0eXBNNEEg"}""",
        ) as HubMessage.CheckinClip

        assertEquals("3", clip.clipId)
        assertEquals("audio/mp4", clip.mime)
        assertArrayEquals(byteArrayOf(0, 0, 0, 0x20) + "ftypM4A ".toByteArray(), clip.audio)
    }

    @Test
    fun aClipIdOfNullMeansTheRecordingWasDeleted() {
        assertEquals(HubMessage.CheckinClipDeleted, parseHubMessage("""{"type": "checkin_clip", "clip_id": null}"""))
    }

    @Test
    fun aBrokenClipGivesNullSoTheSavedOneIsKept() {
        assertNull(parseHubMessage("""{"type": "checkin_clip", "clip_id": "3", "mime": "audio/mp4", "data_b64": "not base64!"}"""))
        assertNull(parseHubMessage("""{"type": "checkin_clip", "clip_id": "3", "mime": "audio/mp4"}"""))
        assertNull(parseHubMessage("""{"type": "checkin_clip"}"""))
    }

    @Test
    fun askPlayedMatchesTheContract() {
        assertEquals(
            """{"type":"ask_played","ask_id":"kitchen-1795698192000","ok":true,""" +
                """"started_ms":1795698192400,"ended_ms":1795698195900}""",
            askPlayedMessage("kitchen-1795698192000", startedMs = 1_795_698_192_400L, endedMs = 1_795_698_195_900L),
        )
        assertEquals(
            """{"type":"ask_played","ask_id":"kitchen-1795698192000","ok":false,"reason":"no_audio_output"}""",
            askNotPlayedMessage("kitchen-1795698192000", reason = "no_audio_output"),
        )
    }

    @Test
    fun brokenMessagesGiveNullInsteadOfCrashing() {
        assertNull(parseHubMessage("not json"))
        assertNull(parseHubMessage("""["welcome"]"""))
        assertNull(parseHubMessage("""{"type": "set_paused"}"""))
        assertNull(parseHubMessage("""{"type": "set_paused", "paused": "yes"}"""))
    }
}
