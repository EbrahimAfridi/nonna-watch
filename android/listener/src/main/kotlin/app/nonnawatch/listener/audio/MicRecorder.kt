package app.nonnawatch.listener.audio

import android.Manifest
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import androidx.annotation.RequiresPermission
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.emitAll
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.flowOn

/**
 * The microphone as a stream of one-second [AudioChunk]s.
 *
 * Recording starts when someone collects [chunks] and stops when they stop collecting, so the
 * microphone is never left on by accident. Problems with the microphone end the flow with a
 * [MicException]; the caller decides whether to try again.
 */
class MicRecorder(private val clock: () -> Long = System::currentTimeMillis) {

    @RequiresPermission(Manifest.permission.RECORD_AUDIO)
    fun chunks(): Flow<AudioChunk> = flow {
        val record = openMicrophone()
        try {
            try {
                record.startRecording()
            } catch (e: IllegalStateException) {
                throw MicException("the microphone could not start", e)
            }
            if (record.recordingState != AudioRecord.RECORDSTATE_RECORDING) {
                throw MicException("the microphone did not start; another app may be using it")
            }
            emitAll(chunksFrom({ buffer, offset, size -> record.read(buffer, offset, size) }, clock))
        } finally {
            record.release() // also stops the recording; Android's microphone indicator turns off
        }
    }.flowOn(Dispatchers.IO) // read() blocks, so it must not run on the main thread

    @RequiresPermission(Manifest.permission.RECORD_AUDIO)
    private fun openMicrophone(): AudioRecord {
        val minBytes = AudioRecord.getMinBufferSize(SAMPLE_RATE, CHANNEL, ENCODING)
        if (minBytes <= 0) {
            // The contract says not to resample on the phone: report it to the hub owner instead.
            throw MicException("this phone cannot record 16 kHz mono audio")
        }
        val record = try {
            // VOICE_RECOGNITION turns off automatic gain control on most phones. With it on, a
            // quiet room is boosted and a thud squashed, which breaks thud and silence detection.
            AudioRecord(
                MediaRecorder.AudioSource.VOICE_RECOGNITION,
                SAMPLE_RATE,
                CHANNEL,
                ENCODING,
                maxOf(minBytes, BUFFER_BYTES),
            )
        } catch (e: IllegalArgumentException) {
            throw MicException("this phone cannot record 16 kHz mono audio", e)
        } catch (e: SecurityException) {
            throw MicException("the microphone permission is missing", e)
        }
        if (record.state != AudioRecord.STATE_INITIALIZED) {
            record.release()
            throw MicException("the microphone could not be opened")
        }
        return record
    }

    private companion object {
        const val CHANNEL = AudioFormat.CHANNEL_IN_MONO
        const val ENCODING = AudioFormat.ENCODING_PCM_16BIT

        /** Room for one second of audio inside Android, so a slow moment on our side loses nothing. */
        const val BUFFER_BYTES = SAMPLES_PER_CHUNK * 2
    }
}

/** Something went wrong with the microphone. [message] is shown on the listener screen. */
class MicException(message: String, cause: Throwable? = null) : Exception(message, cause)

/**
 * The part of [AudioRecord] that [chunksFrom] needs, so tests can stand in for the microphone.
 * Same meaning as `AudioRecord.read(ShortArray, Int, Int)`: how many samples were read, or a
 * negative error code.
 */
fun interface SampleSource {
    fun read(buffer: ShortArray, offset: Int, size: Int): Int
}

/** Read 100 ms at a time, so stopping takes at most a tenth of a second. */
internal const val READ_SAMPLES = SAMPLE_RATE / 10

/**
 * Reads [source] in small pieces and joins them into chunks of exactly [SAMPLES_PER_CHUNK]
 * samples. A read may return fewer samples than asked for; they are kept, never dropped.
 *
 * [clock] is read when a chunk is complete; one second earlier is when its first sample was heard.
 */
internal fun chunksFrom(source: SampleSource, clock: () -> Long): Flow<AudioChunk> = flow {
    while (true) {
        val samples = ShortArray(SAMPLES_PER_CHUNK)
        var filled = 0
        while (filled < samples.size) {
            currentCoroutineContext().ensureActive()
            val read = source.read(samples, filled, minOf(READ_SAMPLES, samples.size - filled))
            if (read <= 0) throw MicException(readProblem(read))
            filled += read
        }
        emit(AudioChunk(captureMs = clock() - CHUNK_MS, samples = samples))
    }
}

/** What an `AudioRecord.read` result of zero or below means, in words for the screen. */
internal fun readProblem(code: Int): String = when (code) {
    0 -> "the microphone sent no sound"
    AudioRecord.ERROR_DEAD_OBJECT -> "the microphone stopped working"
    AudioRecord.ERROR_INVALID_OPERATION -> "the microphone is not recording"
    AudioRecord.ERROR_BAD_VALUE -> "the microphone was read wrongly"
    else -> "the microphone failed (error $code)"
}
