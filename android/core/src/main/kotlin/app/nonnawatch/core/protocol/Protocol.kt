package app.nonnawatch.core.protocol

import app.nonnawatch.core.Room
import java.nio.ByteBuffer
import java.nio.ByteOrder
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

/** A message from the hub that the phone acts on. */
sealed interface HubMessage {
    data class Welcome(val hubId: String, val hubTimeMs: Long, val paused: Boolean) : HubMessage

    data class SetPaused(val paused: Boolean) : HubMessage

    /** For the log; only `bad_hello` is followed by a close (4400). */
    data class Error(val code: String, val message: String) : HubMessage
}

/**
 * Reads a text message from the hub. Gives null for anything the phone does not act on: a type
 * it does not know (the contract says to ignore those), `ask` and `checkin_clip` until A6, and
 * text that is not a valid message. Unknown fields are ignored too.
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
            else -> null
        }
    } catch (e: IllegalArgumentException) {
        null // not JSON, or a field of the wrong kind (SerializationException is one of these)
    }
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
private data class WelcomeJson(
    @SerialName("hub_id") val hubId: String = "",
    @SerialName("hub_time_ms") val hubTimeMs: Long = 0,
    val paused: Boolean = false,
)

@Serializable
private data class SetPausedJson(val paused: Boolean)

@Serializable
private data class ErrorJson(val code: String = "", val message: String = "")
