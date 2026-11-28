package app.nonnawatch.listener.light

import app.nonnawatch.core.protocol.LightState
import kotlin.math.roundToInt
import kotlinx.coroutines.flow.Flow

/** The contract: dark below 10 lux, bright above 30 lux. */
const val DARK_BELOW_LUX = 10f
const val BRIGHT_ABOVE_LUX = 30f

/** Only for the very first reading, which may fall between the two limits. */
private const val FIRST_READING_SPLIT_LUX = 20f

/** What the light sensor is doing, for the screen. */
sealed interface LightStatus {
    /** Started; the sensor has not given a reading yet. */
    data object Waiting : LightStatus

    /** This phone has no light sensor, or Android would not start it. */
    data object NoSensor : LightStatus

    /** [lux] is rounded: the screen shows whole lux. */
    data class Reading(val state: LightState, val lux: Int) : LightStatus
}

/** The room changed from dark to bright or back: what the hub gets in a `light` message. */
data class LightChange(val tsMs: Long, val state: LightState, val lux: Float)

/**
 * Turns lux readings into dark and bright. Between 10 and 30 lux the state stays as it was, so a
 * lamp near one limit does not flicker between the two.
 *
 * The first reading only sets the state: the light was already on (or off) when listening started,
 * so the hub must not get a "light on" for it.
 */
class LightDetector {
    var state: LightState? = null
        private set

    /** Returns the new state when [lux] changed it, and null when it did not. */
    fun update(lux: Float): LightState? {
        val before = state
        if (before == null) {
            state = if (lux < FIRST_READING_SPLIT_LUX) LightState.DARK else LightState.BRIGHT
            return null
        }
        val after = when {
            lux < DARK_BELOW_LUX -> LightState.DARK
            lux > BRIGHT_ABOVE_LUX -> LightState.BRIGHT
            else -> before
        }
        state = after
        return after.takeIf { it != before }
    }
}

/**
 * Follows the light sensor until cancelled. [readings] is null when the phone has none. Every
 * reading goes to [status] for the screen; each change from dark to bright or back goes to
 * [onChange], stamped with [clock].
 */
suspend fun followLight(
    readings: Flow<Float>?,
    clock: () -> Long,
    status: (LightStatus) -> Unit,
    onChange: (LightChange) -> Unit,
) {
    if (readings == null) {
        status(LightStatus.NoSensor)
        return
    }
    status(LightStatus.Waiting)
    val detector = LightDetector()
    readings.collect { lux ->
        if (!lux.isFinite() || lux < 0f) return@collect // a broken reading; the next one counts
        val changed = detector.update(lux)
        status(LightStatus.Reading(detector.state ?: return@collect, lux.roundToInt()))
        if (changed != null) onChange(LightChange(clock(), changed, lux))
    }
    // The readings end only when Android would not start the sensor.
    status(LightStatus.NoSensor)
}
