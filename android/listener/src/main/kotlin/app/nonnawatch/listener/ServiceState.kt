package app.nonnawatch.listener

import app.nonnawatch.core.Room
import app.nonnawatch.listener.hub.LinkState
import app.nonnawatch.listener.voice.QuestionState
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/** What the listening service is doing right now. The service writes it; the screen reads it. */
sealed interface ServiceState {
    /** Not listening. [problem] says why, if the service stopped by itself. */
    data class Stopped(val problem: String? = null) : ServiceState

    /**
     * Listening in [room]: what the microphone and the link to the hub are doing, and the last
     * check-in question the hub asked for ([question] is null until it asks).
     */
    data class Running(
        val room: Room,
        val mic: MicState,
        val hub: LinkState,
        val question: QuestionState? = null,
    ) : ServiceState
}

sealed interface MicState {
    /** [levelPercent] is how loud the last second was, 0 to 100. */
    data class Recording(val secondsRecorded: Long, val levelPercent: Int) : MicState

    /** Paused from the phone or by the family: the microphone is off. */
    data object Paused : MicState

    /** The microphone failed; the service tries again by itself. */
    data class Problem(val message: String) : MicState
}

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
