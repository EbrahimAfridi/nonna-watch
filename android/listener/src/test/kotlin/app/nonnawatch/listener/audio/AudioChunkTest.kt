package app.nonnawatch.listener.audio

import org.junit.Assert.assertEquals
import org.junit.Test

class AudioChunkTest {
    private fun chunkOf(vararg samples: Short) = AudioChunk(captureMs = 0, samples = samples)

    @Test
    fun silenceIsZero() {
        assertEquals(0f, chunkOf(0, 0, 0).level())
    }

    @Test
    fun fullScaleIsOne() {
        assertEquals(1f, chunkOf(Short.MIN_VALUE).level())
        assertEquals(1f, chunkOf(Short.MAX_VALUE).level(), 0.001f)
    }

    @Test
    fun theLoudestSampleCountsWhetherPositiveOrNegative() {
        // Half of full scale is 6 dB down: 54 of the 60 dB shown.
        assertEquals(0.9f, chunkOf(100, 16_384, -200).level(), 0.001f)
        assertEquals(0.9f, chunkOf(100, -16_384, 200).level(), 0.001f)
    }

    @Test
    fun aQuietRoomStillShows() {
        // 1 % of full scale is 40 dB down: a third of the drawing, not a flat line.
        assertEquals(0.333f, chunkOf(328).level(), 0.001f)
    }

    @Test
    fun sixtyDecibelsDownOrQuieterIsDrawnAsSilence() {
        assertEquals(0f, chunkOf(32).level()) // 60.2 dB down
        assertEquals(0f, chunkOf(1, -1).level())
    }
}
