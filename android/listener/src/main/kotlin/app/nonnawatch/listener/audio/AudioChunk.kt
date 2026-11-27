package app.nonnawatch.listener.audio

import kotlin.math.abs

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
 * The loudest sample as a share of full scale, 0 to 100. The status line shows it so you can see
 * the microphone really hears something; A4 replaces the number with a drawn level.
 */
fun AudioChunk.peakPercent(): Int {
    var peak = 0
    for (sample in samples) {
        val size = abs(sample.toInt())
        if (size > peak) peak = size
    }
    return peak * 100 / FULL_SCALE
}

/** abs(Short.MIN_VALUE): the largest a 16-bit sample can be. */
private const val FULL_SCALE = 32_768
