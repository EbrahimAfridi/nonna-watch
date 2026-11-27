package app.nonnawatch.listener.audio

import android.media.AudioRecord
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.take
import kotlinx.coroutines.flow.toList
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class ChunksFromTest {

    /**
     * Stands in for the microphone. Each call to read() uses the next number in [reads]: a
     * positive number delivers up to that many samples, zero or less is returned as an error
     * code. After the list it delivers whatever is asked for. Samples count up 0, 1, 2, ... so a
     * test can see that none were lost or swapped.
     */
    private class FakeMic(private vararg val reads: Int) : SampleSource {
        val askedSizes = mutableListOf<Int>()
        private var call = 0
        private var nextSample = 0

        override fun read(buffer: ShortArray, offset: Int, size: Int): Int {
            askedSizes += size
            val result = reads.getOrElse(call++) { size }
            if (result <= 0) return result
            val count = minOf(result, size)
            repeat(count) { buffer[offset + it] = (nextSample++).toShort() }
            return count
        }
    }

    private val clock = { 1_795_698_193_000L }

    @Test
    fun aChunkIsExactlyOneSecondReadInTenthsOfASecond() = runTest {
        val mic = FakeMic()
        val chunk = chunksFrom(mic, clock).first()

        assertEquals(16_000, chunk.samples.size)
        assertEquals(List(10) { 1_600 }, mic.askedSizes)
    }

    @Test
    fun shortReadsAreJoinedWithoutLosingOrSwappingSamples() = runTest {
        val chunks = chunksFrom(FakeMic(700, 1, 1_599, 3, 10_000, 1_200), clock).take(2).toList()

        val samples = chunks.flatMap { it.samples.toList() }
        assertEquals(List(32_000) { it.toShort() }, samples)
    }

    @Test
    fun captureTimeIsOneSecondBeforeTheChunkWasComplete() = runTest {
        val chunk = chunksFrom(FakeMic(), clock).first()

        // The worked example in docs/api-contract.md: 2026-11-26 14:03:12 +01:00.
        assertEquals(1_795_698_192_000L, chunk.captureMs)
    }

    @Test
    fun aMicrophoneErrorEndsTheFlowWithItsMeaning() = runTest {
        val error = runCatching {
            chunksFrom(FakeMic(1_600, AudioRecord.ERROR_DEAD_OBJECT), clock).first()
        }.exceptionOrNull()

        assertTrue(error is MicException)
        assertEquals("the microphone stopped working", error?.message)
    }

    @Test
    fun aReadOfNothingIsAProblemNotALoopForever() = runTest {
        val error = runCatching { chunksFrom(FakeMic(0), clock).first() }.exceptionOrNull()

        assertTrue(error is MicException)
        assertEquals("the microphone sent no sound", error?.message)
    }

    @Test
    fun unknownErrorCodesAreShownAsNumbers() {
        assertEquals("the microphone failed (error -99)", readProblem(-99))
    }
}
