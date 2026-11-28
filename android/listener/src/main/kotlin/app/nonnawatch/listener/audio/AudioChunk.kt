package app.nonnawatch.listener.audio

import kotlin.math.abs
import kotlin.math.log10

/** 16 kHz mono 16-bit, the only format the hub accepts (docs/api-contract.md). */
const val SAMPLE_RATE = 16_000

/** One chunk is one second of audio, the payload of one audio frame to the hub. */
const val SAMPLES_PER_CHUNK = SAMPLE_RATE
const val CHUNK_MS = 1_000L

/**
 * One second of microphone audio. It lives in memory only: the app never writes audio to disk or
 * to the log.
 *
 * [captureMs] is the Unix time in ms of the first sample, taken when the recording finished and
 * moved back by one second, as the contract asks. A3 sends it as the frame's `capture_ms`, and
 * Experiment 1 measures alert latency from it.
 */
class AudioChunk(val captureMs: Long, val samples: ShortArray)

/**
 * How loud the loudest moment of this second was, from 0 (60 dB or more below full scale, or
 * silence) to 1 (full scale), for the level drawing on the screen.
 *
 * Decibels, not a plain share of full scale: in a quiet room the loudest sample is about 1 % of
 * full scale, which would draw as nothing. On this scale a quiet room is about a third and speech
 * near the phone about three quarters, so both show.
 */
fun AudioChunk.level(): Float {
    var peak = 0
    for (sample in samples) {
        val size = abs(sample.toInt())
        if (size > peak) peak = size
    }
    if (peak == 0) return 0f
    val decibels = 20 * log10(peak.toDouble() / FULL_SCALE)
    return ((decibels + LEVEL_RANGE_DB) / LEVEL_RANGE_DB).toFloat().coerceIn(0f, 1f)
}

/** abs(Short.MIN_VALUE): the largest a 16-bit sample can be. */
private const val FULL_SCALE = 32_768

/** The drawing shows the top 60 dB; anything quieter is drawn as silence. */
private const val LEVEL_RANGE_DB = 60.0
