package app.nonnawatch.core.protocol

import app.nonnawatch.core.Room
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.Base64
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/*
 * The listener ↔ hub protocol, version 1. The spec is docs/api-contract.md; the hub's side is
 * hub/nonna_hub/protocol.py. A change here is a change to the contract: agree it in the group
 * and record it in DECISIONS.md first.
 */

const val PROTOCOL_VERSION = 1
const val SAMPLE_RATE = 16_000

/** One frame is one second of audio. */
const val FRAME_SAMPLES = SAMPLE_RATE
const val FRAME_HEADER_BYTES = 12

/** 32,012 bytes. The hub drops a frame of any other length. */
const val FRAME_BYTES = FRAME_HEADER_BYTES + FRAME_SAMPLES * 2

/** WebSocket close codes and the HTTP status the hub uses ("Close codes" in the contract). */
object CloseCodes {
    /** The phone stopped listening. */
    const val NORMAL = 1000

    /** Bad hello (unknown protocol, wrong sample rate, unknown room) or audio before hello. */
    const val BAD_HELLO = 4400

    /** A newer connection for the same room, or with the same device id, replaced this one. */
    const val REPLACED = 4409

    /** The hub refused the upgrade: wrong token. */
    const val HTTP_WRONG_TOKEN = 403
}

/**
 * One binary audio frame: `capture_ms` (int64), `seq` (uint32), then 16,000 samples (int16), all
 * little-endian. ByteBuffer is big-endian by default; without `.order(LITTLE_ENDIAN)` the hub
 * hears loud noise.
 */
fun audioFrame(captureMs: Long, seq: Int, samples: ShortArray): ByteArray {
    require(samples.size == FRAME_SAMPLES) {
        "a frame holds $FRAME_SAMPLES samples, got ${samples.size}"
    }
    val buffer = ByteBuffer.allocate(FRAME_BYTES).order(ByteOrder.LITTLE_ENDIAN)
    buffer.putLong(captureMs)
    buffer.putInt(seq)
    buffer.asShortBuffer().put(samples)
    return buffer.array()
}

/** The first message on every connection, exactly once. */
fun helloMessage(deviceId: String, room: Room, appVersion: String, deviceModel: String): String =
    json.encodeToString(
        HelloJson.serializer(),
        HelloJson(deviceId = deviceId, room = room.id, appVersion = appVersion, deviceModel = deviceModel),
    )

/** Every 30 s, and at once whenever [paused] changes. */
fun heartbeatMessage(tsMs: Long, batteryPct: Int, charging: Boolean, paused: Boolean): String =
    json.encodeToString(
        HeartbeatJson.serializer(),
        HeartbeatJson(
            tsMs = tsMs,
            batteryPct = batteryPct.coerceIn(0, 100),
            charging = charging,
            paused = paused,
        ),
    )

/** How light the room is, as the `light` message names it. */
enum class LightState(val wire: String) {
    DARK("dark"),
    BRIGHT("bright"),
}

/**
 * Only when the room changes from dark to bright or back, not for every reading. [lux] is the
 * reading that made the change. The hub refuses a negative lux, and JSON has no "not a number".
 */
fun lightMessage(tsMs: Long, state: LightState, lux: Float): String =
    json.encodeToString(
        LightJson.serializer(),
        LightJson(tsMs = tsMs, state = state.wire, lux = if (lux.isFinite()) lux.coerceAtLeast(0f) else 0f),
    )

/** After the check-in question has played: when it started and ended, in this phone's clock. */
fun askPlayedMessage(askId: String, startedMs: Long, endedMs: Long): String =
    json.encodeToString(
        AskPlayedJson.serializer(),
        AskPlayedJson(askId = askId, startedMs = startedMs, endedMs = endedMs),
    )

/**
 * When the check-in question could not play. The hub then alerts the family at once instead of
 * waiting 20 s. [reason] must be short printable ASCII, like `no_audio_output`.
 */
fun askNotPlayedMessage(askId: String, reason: String): String =
    json.encodeToString(AskNotPlayedJson.serializer(), AskNotPlayedJson(askId = askId, reason = reason))

/** A message from the hub that the phone acts on. */
sealed interface HubMessage {
    data class Welcome(val hubId: String, val hubTimeMs: Long, val paused: Boolean) : HubMessage

    data class SetPaused(val paused: Boolean) : HubMessage

    /** For the log; only `bad_hello` is followed by a close (4400). */
    data class Error(val code: String, val message: String) : HubMessage

    /**
     * Play the check-in question now: the family's recording if there is one, otherwise [text]
     * spoken in [lang] (a language tag like `it-IT`). [reason] is only for the log.
     */
    data class Ask(val askId: String, val reason: String, val text: String, val lang: String) : HubMessage

    /** The family's recorded check-in question; it replaces the one saved before. */
    class CheckinClip(val clipId: String, val mime: String, val audio: ByteArray) : HubMessage

    /** The family deleted their recording: speak the question's text again. */
    data object CheckinClipDeleted : HubMessage
}

/**
 * Reads a text message from the hub. Gives null for anything the phone does not act on: a type
 * it does not know (the contract says to ignore those), and text that is not a valid message.
 * Unknown fields are ignored too.
 */
fun parseHubMessage(text: String): HubMessage? {
    return try {
        val message = json.parseToJsonElement(text) as? JsonObject ?: return null
        val type = (message["type"] as? JsonPrimitive)?.takeIf { it.isString }?.content
        when (type) {
            "welcome" -> json.decodeFromJsonElement(WelcomeJson.serializer(), message)
                .let { HubMessage.Welcome(it.hubId, it.hubTimeMs, it.paused) }
            "set_paused" -> HubMessage.SetPaused(
                json.decodeFromJsonElement(SetPausedJson.serializer(), message).paused,
            )
            "error" -> json.decodeFromJsonElement(ErrorJson.serializer(), message)
                .let { HubMessage.Error(it.code, it.message) }
            "ask" -> json.decodeFromJsonElement(AskJson.serializer(), message)
                .let { HubMessage.Ask(it.askId, it.reason, it.text, it.lang) }
            "checkin_clip" -> checkinClip(json.decodeFromJsonElement(CheckinClipJson.serializer(), message))
            else -> null
        }
    } catch (e: IllegalArgumentException) {
        // Not JSON, a field of the wrong kind (SerializationException is one of these), or a
        // clip whose data is not valid base64.
        null
    }
}

private fun checkinClip(clip: CheckinClipJson): HubMessage? {
    val clipId = clip.clipId ?: return HubMessage.CheckinClipDeleted
    val audio = Base64.getDecoder().decode(clip.dataB64)
    // An empty recording would replace a good one with silence, so it counts as broken.
    return if (audio.isEmpty()) null else HubMessage.CheckinClip(clipId, clip.mime, audio)
}

private val json = Json {
    encodeDefaults = true // type, protocol and sample_rate have defaults but must still be sent
    ignoreUnknownKeys = true // the contract: either side may add optional fields
}

@Serializable
private data class HelloJson(
    val type: String = "hello",
    val protocol: Int = PROTOCOL_VERSION,
    @SerialName("device_id") val deviceId: String,
    val room: String,
    @SerialName("sample_rate") val sampleRate: Int = SAMPLE_RATE,
    @SerialName("app_version") val appVersion: String,
    @SerialName("device_model") val deviceModel: String,
)

@Serializable
private data class HeartbeatJson(
    val type: String = "heartbeat",
    @SerialName("ts_ms") val tsMs: Long,
    @SerialName("battery_pct") val batteryPct: Int,
    val charging: Boolean,
    val paused: Boolean,
)

@Serializable
private data class LightJson(
    val type: String = "light",
    @SerialName("ts_ms") val tsMs: Long,
    val state: String,
    val lux: Float,
)

@Serializable
private data class WelcomeJson(
    @SerialName("hub_id") val hubId: String = "",
    @SerialName("hub_time_ms") val hubTimeMs: Long = 0,
    val paused: Boolean = false,
)

@Serializable
private data class SetPausedJson(val paused: Boolean)

@Serializable
private data class ErrorJson(val code: String = "", val message: String = "")

@Serializable
private data class AskPlayedJson(
    val type: String = "ask_played",
    @SerialName("ask_id") val askId: String,
    val ok: Boolean = true,
    @SerialName("started_ms") val startedMs: Long,
    @SerialName("ended_ms") val endedMs: Long,
)

@Serializable
private data class AskNotPlayedJson(
    val type: String = "ask_played",
    @SerialName("ask_id") val askId: String,
    val ok: Boolean = false,
    val reason: String,
)

// Without an id the phone could not answer, and without the text and the language it could not
// speak, so those are required. Ignoring such an ask is safe: the hub alerts after 20 s.
@Serializable
private data class AskJson(
    @SerialName("ask_id") val askId: String,
    val reason: String = "",
    val text: String,
    val lang: String,
)

// clip_id is required but may be null (null means the family deleted the recording).
@Serializable
private data class CheckinClipJson(
    @SerialName("clip_id") val clipId: String?,
    val mime: String = "",
    @SerialName("data_b64") val dataB64: String = "",
)
