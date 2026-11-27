package app.nonnawatch.listener

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import app.nonnawatch.core.Room
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.flow.update

/** Everything the listener screen shows. The screen only draws this; it decides nothing. */
data class ListenerUiState(
    val room: Room = Room.KITCHEN,
    val listening: Boolean = false,
    val status: String = NOT_LISTENING,
)

/**
 * MVVM: the ViewModel holds the state and survives screen rotation; the screen sends events
 * (like [selectRoom] or [start]) and redraws when [state] changes.
 *
 * The service keeps running when the screen closes, so whether we are listening comes from
 * [control], not from here. Only the room picked before starting lives in the ViewModel.
 */
class ListenerViewModel(private val control: ListenerControl) : ViewModel() {
    private val choices = MutableStateFlow(Choices())

    val state: StateFlow<ListenerUiState> = combine(choices, control.state, ::toUiState)
        .stateIn(
            viewModelScope,
            SharingStarted.Eagerly,
            toUiState(choices.value, control.state.value),
        )

    /** The room is sent to the hub when listening starts, so it cannot change while listening. */
    fun selectRoom(room: Room) {
        if (!state.value.listening) choices.update { it.copy(room = room) }
    }

    /** Call once the microphone permission is granted. */
    fun start() {
        if (state.value.listening) return
        choices.update { it.copy(micPermissionDenied = false) }
        control.start(choices.value.room)
    }

    fun stop() = control.stop()

    fun micPermissionDenied() {
        choices.update { it.copy(micPermissionDenied = true) }
    }
}

/** What the person chose on this screen, as opposed to what the service is doing. */
private data class Choices(
    val room: Room = Room.KITCHEN,
    val micPermissionDenied: Boolean = false,
)

private fun toUiState(choices: Choices, service: ServiceState): ListenerUiState = when (service) {
    is ServiceState.Stopped -> ListenerUiState(
        room = choices.room,
        listening = false,
        status = when {
            choices.micPermissionDenied -> MIC_PERMISSION_DENIED
            service.problem != null -> "$NOT_LISTENING: ${service.problem}"
            else -> NOT_LISTENING
        },
    )
    is ServiceState.Listening -> ListenerUiState(
        room = service.room,
        listening = true,
        status = "Listening · ${formatDuration(service.secondsRecorded)} recorded · " +
            "level ${service.levelPercent} %",
    )
    is ServiceState.MicProblem -> ListenerUiState(
        room = service.room,
        listening = true,
        status = "Microphone problem: ${service.message}. Trying again…",
    )
}

/** "42 s", "3 min 5 s", "1 h 2 min": readable during the one-hour screen-off test (M2). */
internal fun formatDuration(totalSeconds: Long): String {
    val hours = totalSeconds / 3600
    val minutes = totalSeconds % 3600 / 60
    val seconds = totalSeconds % 60
    return when {
        hours > 0 -> "$hours h $minutes min"
        minutes > 0 -> "$minutes min $seconds s"
        else -> "$seconds s"
    }
}

internal const val NOT_LISTENING = "Not listening"
internal const val MIC_PERMISSION_DENIED =
    "Not listening: the microphone permission is needed. " +
        "Allow it in Settings → Apps → Nonna Listener → Permissions."
