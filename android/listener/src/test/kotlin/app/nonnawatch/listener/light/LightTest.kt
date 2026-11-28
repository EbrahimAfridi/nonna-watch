package app.nonnawatch.listener.light

import app.nonnawatch.core.protocol.LightState
import kotlinx.coroutines.flow.emptyFlow
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class LightTest {

    /** What each reading in turn made the detector report: the new state, or null for no change. */
    private fun changesFor(vararg lux: Float): List<LightState?> {
        val detector = LightDetector()
        return lux.map(detector::update)
    }

    @Test
    fun theFirstReadingOnlySetsTheState() {
        // The lamp was already on when listening started: no "light on" for that.
        val detector = LightDetector()
        assertNull(detector.update(200f))
        assertEquals(LightState.BRIGHT, detector.state)
    }

    @Test
    fun darkBelowTenAndBrightAboveThirty() {
        assertEquals(
            listOf(null, LightState.DARK, LightState.BRIGHT),
            changesFor(200f, 3f, 150f),
        )
    }

    @Test
    fun betweenTheLimitsTheStateStays() {
        // A lamp near a limit does not flicker: 10 is not below 10, 30 is not above 30.
        assertEquals(
            listOf(null, null, null, null, LightState.DARK),
            changesFor(200f, 20f, 10f, 15f, 9.9f),
        )
        assertEquals(
            listOf(null, null, null, LightState.BRIGHT),
            changesFor(2f, 25f, 30f, 30.1f),
        )
    }

    @Test
    fun aFirstReadingBetweenTheLimitsIsSplitAtTwenty() {
        val dim = LightDetector().apply { update(15f) }
        assertEquals(LightState.DARK, dim.state)
        assertEquals(LightState.BRIGHT, dim.update(31f))

        val lit = LightDetector().apply { update(25f) }
        assertEquals(LightState.BRIGHT, lit.state)
        assertEquals(LightState.DARK, lit.update(5f))
    }

    @Test
    fun followingTheSensorShowsEveryReadingAndSendsOnlyChanges() = runTest {
        val statuses = mutableListOf<LightStatus>()
        val changes = mutableListOf<LightChange>()
        var now = 1_000L

        followLight(
            readings = flowOf(112.4f, 80f, 3f, 4.6f),
            clock = { now++ },
            status = { statuses += it },
            onChange = { changes += it },
        )

        assertEquals(
            listOf(
                LightStatus.Waiting,
                LightStatus.Reading(LightState.BRIGHT, lux = 112),
                LightStatus.Reading(LightState.BRIGHT, lux = 80),
                LightStatus.Reading(LightState.DARK, lux = 3),
                LightStatus.Reading(LightState.DARK, lux = 5),
                LightStatus.NoSensor, // the test's readings end, as when the sensor would not start
            ),
            statuses,
        )
        assertEquals(listOf(LightChange(tsMs = 1_000L, state = LightState.DARK, lux = 3f)), changes)
    }

    @Test
    fun brokenReadingsAreSkipped() = runTest {
        val changes = mutableListOf<LightChange>()

        followLight(
            readings = flowOf(Float.NaN, -1f, 200f, Float.POSITIVE_INFINITY, 2f),
            clock = { 0L },
            status = {},
            onChange = { changes += it },
        )

        assertEquals(listOf(LightChange(tsMs = 0L, state = LightState.DARK, lux = 2f)), changes)
    }

    @Test
    fun aPhoneWithoutALightSensorSaysSo() = runTest {
        val statuses = mutableListOf<LightStatus>()
        followLight(readings = null, clock = { 0L }, status = { statuses += it }, onChange = {})
        assertEquals(listOf<LightStatus>(LightStatus.NoSensor), statuses)
    }

    @Test
    fun aSensorThatWouldNotStartSaysSo() = runTest {
        val statuses = mutableListOf<LightStatus>()
        followLight(readings = emptyFlow(), clock = { 0L }, status = { statuses += it }, onChange = {})
        assertEquals(listOf(LightStatus.Waiting, LightStatus.NoSensor), statuses)
    }
}
