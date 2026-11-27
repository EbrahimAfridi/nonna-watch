package app.nonnawatch.listener

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import app.nonnawatch.core.Room
import app.nonnawatch.listener.hub.LinkState
import app.nonnawatch.listener.settings.ListenerSettings
import app.nonnawatch.listener.settings.SettingsStore
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.flow.update

/** Everything the listener screen shows, apart from the two text fields. */
data class ListenerUiState(
    val room: Room = Room.KITCHEN,
    val listening: Boolean = false,
    val paused: Boolean = false,
    /** The microphone, or why the phone is not listening. */
    val status: String = NOT_LISTENING,
    /** The link to the hub; empty while not listening. */
    val hubStatus: String = "",
)

/**
 * MVVM: the ViewModel holds the state and survives screen rotation; the screen sends events
 * (like [selectRoom] or [start]) and redraws when [state] changes.
 *
 * The service keeps running when the screen closes, so what the phone is doing comes from
 * [control]. The settings come from [settings] and are saved as soon as they change.
 */
class ListenerViewModel(
    private val control: ListenerControl,
    private val settings: SettingsStore,
) : ViewModel() {

    private val saved = settings.load()

    // The two text fields read these directly: a Compose text field needs its text updated at
    // once, which a flow cannot promise.
    var hubUrl by mutableStateOf(saved.hubUrl)
        private set
    var token by mutableStateOf(saved.token)
        private set

    private val form = MutableStateFlow(Form(room = saved.room))

    val state: StateFlow<ListenerUiState> = combine(form, control.state, ::toUiState)
        .stateIn(viewModelScope, SharingStarted.Eagerly, toUiState(form.value, control.state.value))

    // The hub learns the room, address and token once, when the phone connects, so none of them
    // can change while listening.
    fun selectRoom(room: Room) {
        if (state.value.listening) return
        form.update { it.copy(room = room) }
        saveEdit()
    }

    fun editHubUrl(text: String) {
        if (state.value.listening) return
        hubUrl = text
        saveEdit()
    }

    fun editToken(text: String) {
        if (state.value.listening) return
        token = text
        saveEdit()
    }

    /**
     * Checks the settings before Android is asked for the microphone. On false the status says
     * what is missing.
     */
    fun readyToStart(): Boolean {
        if (state.value.listening) return false
        val problem = currentSettings().problem()
        form.update { it.copy(notice = problem?.let { "$NOT_LISTENING: $it" }) }
        return problem == null
    }

    /** Call once the microphone permission is granted. */
    fun start() {
        if (state.value.listening) return
        form.update { it.copy(notice = null) }
        control.start()
    }

    fun stop() = control.stop()

    fun togglePause() {
        if (state.value.listening) control.setPaused(!state.value.paused)
    }

    fun micPermissionDenied() {
        form.update { it.copy(notice = MIC_PERMISSION_DENIED) }
    }

    private fun currentSettings() = ListenerSettings(hubUrl, token, form.value.room)

    /** Saves at once, and clears an old message such as "enter the token". */
    private fun saveEdit() {
        settings.save(currentSettings())
        form.update { it.copy(notice = null) }
    }
}

/** What the person chose on this screen, apart from the text fields. */
private data class Form(
    val room: Room,
    /** A message for the person, such as a missing setting or a refused permission. */
    val notice: String? = null,
)

private fun toUiState(form: Form, service: ServiceState): ListenerUiState = when (service) {
    is ServiceState.Stopped -> ListenerUiState(
        room = form.room,
        listening = false,
        status = form.notice ?: service.problem?.let { "$NOT_LISTENING: $it" } ?: NOT_LISTENING,
    )
    is ServiceState.Running -> ListenerUiState(
        room = service.room,
        listening = true,
        paused = service.mic is MicState.Paused,
        status = micStatus(service.mic),
        hubStatus = hubStatus(service.hub),
    )
}

private fun micStatus(mic: MicState): String = when (mic) {
    is MicState.Recording ->
        "Listening · ${formatDuration(mic.secondsRecorded)} recorded · level ${mic.levelPercent} %"
    MicState.Paused -> "Paused: the microphone is off"
    is MicState.Problem -> "Microphone problem: ${mic.message}. Trying again…"
}

private fun hubStatus(hub: LinkState): String = when (hub) {
    LinkState.Connecting -> "Hub: connecting…"
    is LinkState.Connected -> {
        val name = hub.hubId.ifBlank { "the hub" }
        "Hub: connected to $name · ${formatDuration(hub.secondsSent)} sent"
    }
    is LinkState.Waiting -> "Hub: ${hub.reason}. Trying again in ${hub.retryInSeconds} s"
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
