package app.nonnawatch.listener

import androidx.lifecycle.ViewModel
import app.nonnawatch.core.Room
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update

/** Everything the listener screen shows. The screen only draws this; it decides nothing. */
data class ListenerUiState(
    val room: Room = Room.KITCHEN,
    val status: String = "Not listening",
)

/**
 * MVVM: the ViewModel holds the state and survives screen rotation; the screen sends events
 * (like [selectRoom]) and redraws when [state] changes. A2 adds start/stop of the service here.
 */
class ListenerViewModel : ViewModel() {
    private val _state = MutableStateFlow(ListenerUiState())
    val state: StateFlow<ListenerUiState> = _state.asStateFlow()

    fun selectRoom(room: Room) {
        _state.update { it.copy(room = room) }
    }
}
