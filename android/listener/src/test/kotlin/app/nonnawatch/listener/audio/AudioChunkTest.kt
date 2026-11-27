package app.nonnawatch.listener.audio

import org.junit.Assert.assertEquals
import org.junit.Test

class AudioChunkTest {
    private fun chunkOf(vararg samples: Short) = AudioChunk(captureMs = 0, samples = samples)

    @Test
    fun silenceIsZero() {
        assertEquals(0, chunkOf(0, 0, 0).peakPercent())
    }

    @Test
    fun theLoudestSampleCountsWhetherPositiveOrNegative() {
        assertEquals(50, chunkOf(100, 16_384, -200).peakPercent())
        assertEquals(50, chunkOf(100, -16_384, 200).peakPercent())
    }

    @Test
    fun fullScaleIsOneHundred() {
        assertEquals(100, chunkOf(Short.MIN_VALUE).peakPercent())
    }
}
