package app.nonnawatch.listener

import app.nonnawatch.core.Room
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/** What the listening service is doing right now. The service writes it; the screen reads it. */
sealed interface ServiceState {
    /** Not listening. [problem] says why, if the service stopped by itself. */
    data class Stopped(val problem: String? = null) : ServiceState

    /** Recording. [levelPercent] is how loud the last second was, 0 to 100. */
    data class Listening(
        val room: Room,
        val secondsRecorded: Long,
        val levelPercent: Int,
    ) : ServiceState

    /** The service is running but the microphone failed; it tries again by itself. */
    data class MicProblem(val room: Room, val message: String) : ServiceState
}

/**
 * The one copy of [ServiceState] in the app's process. When Android ends the process, the service
 * is gone too, and a new process starts from "stopped", which is then correct.
 */
object ServiceStateHolder {
    private val _state = MutableStateFlow<ServiceState>(ServiceState.Stopped())
    val state: StateFlow<ServiceState> = _state.asStateFlow()

    internal fun set(state: ServiceState) {
        _state.value = state
    }
}
