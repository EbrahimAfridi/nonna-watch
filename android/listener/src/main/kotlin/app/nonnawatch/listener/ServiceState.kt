package app.nonnawatch.listener

import app.nonnawatch.core.Room
import app.nonnawatch.listener.hub.LinkState
import app.nonnawatch.listener.light.LightStatus
import app.nonnawatch.listener.voice.QuestionState
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/** What the listening service is doing right now. The service writes it; the screen reads it. */
sealed interface ServiceState {
    /** Not listening. [problem] says why, if the service stopped by itself. */
    data class Stopped(val problem: String? = null) : ServiceState

    /**
     * Listening in [room]: what the microphone and the link to the hub are doing, the last
     * check-in question the hub asked for ([question] is null until it asks), and the light
     * sensor ([light] is null while paused).
     */
    data class Running(
        val room: Room,
        val mic: MicState,
        val hub: LinkState,
        val question: QuestionState? = null,
        val light: LightStatus? = null,
    ) : ServiceState
}

sealed interface MicState {
    /**
     * [levels] is how loud each of the last seconds was (see AudioChunk.level), oldest first, at
     * most [LEVEL_SECONDS] of them, for the level drawing.
     */
    data class Recording(val secondsRecorded: Long, val levels: List<Float> = emptyList()) : MicState {
        /** One more second, heard at [level]; the oldest drops out after a minute. */
        fun plusSecond(level: Float) =
            Recording(secondsRecorded + 1, (levels + level).takeLast(LEVEL_SECONDS))
    }

    /** Paused from the phone or by the family: the microphone and the light sensor are off. */
    data object Paused : MicState

    /** The microphone failed; the service tries again by itself. */
    data class Problem(val message: String) : MicState
}

/** The level drawing shows the last minute, one bar per second. */
const val LEVEL_SECONDS = 60

/**
 * The one copy of the service's state in the app's process. When Android ends the process, the
 * service is gone too, and a new process starts from "stopped", which is then correct.
 */
object ServiceStateHolder {
    private val _state = MutableStateFlow<ServiceState>(ServiceState.Stopped())
    val state: StateFlow<ServiceState> = _state.asStateFlow()

    /**
     * The pause switch. The Pause button and the hub (welcome, set_paused) flip it; the service
     * turns the microphone off and on to match, and tells the hub at once.
     */
    val paused = MutableStateFlow(false)

    internal fun set(state: ServiceState) {
        _state.value = state
    }
}
