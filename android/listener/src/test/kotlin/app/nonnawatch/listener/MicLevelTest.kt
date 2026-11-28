package app.nonnawatch.listener

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** The level drawing's geometry and the minute of levels it is drawn from. */
class MicLevelTest {

    @Test
    fun eachSecondAddsALevelAndTheDrawingKeepsTheLastMinute() {
        var recording = MicState.Recording(secondsRecorded = 100)

        repeat(61) { second -> recording = recording.plusSecond(second / 100f) }

        assertEquals(161L, recording.secondsRecorded)
        assertEquals(60, recording.levels.size)
        assertEquals(0.01f, recording.levels.first()) // the very first second has dropped out
        assertEquals(0.6f, recording.levels.last())
    }

    @Test
    fun theNewestSecondIsOnTheRightAndTheBarsFillInFromThere() {
        // 4 places of 10 px; bars are 7 px wide, centred in their place.
        val bars = levelBars(listOf(0.5f, 1f), slots = 4, width = 40f, height = 20f, minHeight = 1f)

        assertEquals(
            listOf(
                Bar(left = 21.5f, top = 10f, width = 7f, height = 10f),
                Bar(left = 31.5f, top = 0f, width = 7f, height = 20f),
            ),
            bars,
        )
    }

    @Test
    fun aSilentSecondIsAThinLineNotNothing() {
        val bar = levelBars(listOf(0f), slots = 1, width = 10f, height = 20f, minHeight = 2f).single()
        assertEquals(2f, bar.height)
        assertEquals(18f, bar.top) // standing on the bottom edge
    }

    @Test
    fun moreLevelsThanPlacesShowsTheNewest() {
        val bars = levelBars(listOf(0.25f, 0.5f, 0.75f), slots = 2, width = 20f, height = 10f, minHeight = 0f)
        assertEquals(listOf(5f, 7.5f), bars.map { it.height })
        assertEquals(1.5f, bars.first().left)
    }

    @Test
    fun levelsOutsideZeroToOneStayInsideTheBox() {
        val bars = levelBars(listOf(-1f, 2f), slots = 2, width = 20f, height = 10f, minHeight = 1f)
        assertEquals(listOf(1f, 10f), bars.map { it.height })
        assertTrue(bars.all { it.top >= 0f })
    }

    @Test
    fun anEmptyOrUnmeasuredBoxDrawsNothing() {
        assertTrue(levelBars(emptyList(), slots = 60, width = 300f, height = 50f, minHeight = 2f).isEmpty())
        assertTrue(levelBars(listOf(0.5f), slots = 60, width = 0f, height = 50f, minHeight = 2f).isEmpty())
    }
}
