package app.nonnawatch.listener

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import app.nonnawatch.core.Room
import app.nonnawatch.listener.hub.LinkState
import app.nonnawatch.listener.light.LightStatus
import app.nonnawatch.listener.settings.ListenerSettings
import app.nonnawatch.listener.settings.SettingsStore
import app.nonnawatch.listener.voice.AskResult
import app.nonnawatch.listener.voice.NotPlayedReason
import app.nonnawatch.listener.voice.QuestionLanguage
import app.nonnawatch.listener.voice.QuestionState
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/** Everything the listener screen shows, apart from the two text fields. */
data class ListenerUiState(
    val room: Room = Room.KITCHEN,
    val listening: Boolean = false,
    val paused: Boolean = false,
    /** The microphone, or why the phone is not listening. */
    val status: String = NOT_LISTENING,
    /** How loud the last seconds were, for the level drawing; null hides it (not recording). */
    val micLevels: List<Float>? = null,
    /** The link to the hub; empty while not listening. */
    val hubStatus: String = "",
    /** The light sensor; empty while not listening or paused. */
    val lightStatus: String = "",
    /** The last check-in question the hub asked for; empty until it asks. */
    val questionStatus: String = "",
    /** The language the Test button speaks in. */
    val testLanguage: QuestionLanguage = QuestionLanguage.ITALIAN,
    /** True while the Test button's question is playing. */
    val testing: Boolean = false,
    /** How the last test went; empty before the first one. */
    val testStatus: String = "",
)

/**
 * MVVM: the ViewModel holds the state and survives screen rotation; the screen sends events
 * (like [selectRoom] or [start]) and redraws when [state] changes.
 *
 * The service keeps running when the screen closes, so what the phone is doing comes from
 * [control]. The settings come from [settings] and are saved as soon as they change. Times are
 * shown in [zone].
 */
class ListenerViewModel(
    private val control: ListenerControl,
    private val settings: SettingsStore,
    private val zone: ZoneId = ZoneId.systemDefault(),
) : ViewModel() {

    private val saved = settings.load()

    // The two text fields read these directly: a Compose text field needs its text updated at
    // once, which a flow cannot promise.
    var hubUrl by mutableStateOf(saved.hubUrl)
        private set
    var token by mutableStateOf(saved.token)
        private set

    private val form = MutableStateFlow(Form(room = saved.room))
    private val test = MutableStateFlow(QuestionTest())

    val state: StateFlow<ListenerUiState> = combine(form, test, control.state, ::toUiState)
        .stateIn(viewModelScope, SharingStarted.Eagerly, toUiState(form.value, test.value, control.state.value))

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

    fun selectTestLanguage(language: QuestionLanguage) {
        if (test.value.running) return
        test.update { it.copy(language = language, result = null) }
    }

    /** Speaks the question in the chosen language, so a missing voice shows up before the demo. */
    fun testQuestion() {
        if (test.value.running) return
        val language = test.value.language
        test.update { it.copy(running = true, result = null) }
        viewModelScope.launch {
            val result = control.testQuestion(language)
            test.update { it.copy(running = false, result = result) }
        }
    }

    private fun currentSettings() = ListenerSettings(hubUrl, token, form.value.room)

    /** Saves at once, and clears an old message such as "enter the token". */
    private fun saveEdit() {
        settings.save(currentSettings())
        form.update { it.copy(notice = null) }
    }

    private fun toUiState(form: Form, test: QuestionTest, service: ServiceState): ListenerUiState {
        val screen = ListenerUiState(
            room = form.room,
            testLanguage = test.language,
            testing = test.running,
            testStatus = testStatus(test),
        )
        return when (service) {
            is ServiceState.Stopped -> screen.copy(
                status = form.notice ?: service.problem?.let { "$NOT_LISTENING: $it" } ?: NOT_LISTENING,
            )
            is ServiceState.Running -> screen.copy(
                room = service.room,
                listening = true,
                paused = service.mic is MicState.Paused,
                status = micStatus(service.mic),
                micLevels = (service.mic as? MicState.Recording)?.levels,
                hubStatus = hubStatus(service.hub),
                lightStatus = service.light?.let(::lightStatus).orEmpty(),
                questionStatus = service.question?.let(::questionStatus).orEmpty(),
            )
        }
    }

    private fun questionStatus(question: QuestionState): String = when (question) {
        QuestionState.Playing -> "Check-in question: playing…"
        is QuestionState.Finished -> when (val result = question.result) {
            is AskResult.Played -> "Check-in question: played at ${clockTime(result.endedMs, zone)}"
            is AskResult.NotPlayed -> "Check-in question: not played, ${notPlayedText(result.reason)}"
        }
    }
}

/** What the person chose on this screen, apart from the text fields and the test. */
private data class Form(
    val room: Room,
    /** A message for the person, such as a missing setting or a refused permission. */
    val notice: String? = null,
)

/** The Test button: its language, whether it is playing, and how the last test went. */
private data class QuestionTest(
    val language: QuestionLanguage = QuestionLanguage.ITALIAN,
    val running: Boolean = false,
    val result: AskResult? = null,
)

private fun testStatus(test: QuestionTest): String {
    val name = "Test (${test.language.label})"
    return when (val result = test.result) {
        null -> if (test.running) "$name: playing…" else ""
        is AskResult.Played -> "$name: played, ${tenthsOfSeconds(result.endedMs - result.startedMs)}"
        is AskResult.NotPlayed -> "$name: not played, ${notPlayedText(result.reason)}"
    }
}

/** What a [NotPlayedReason] means, for the person holding the phone. */
internal fun notPlayedText(reason: String): String = when (reason) {
    NotPlayedReason.NO_AUDIO_OUTPUT -> "the alarm volume is at zero, or Do Not Disturb is on total silence"
    NotPlayedReason.NO_TEXT_TO_SPEECH -> "this phone has no text-to-speech"
    NotPlayedReason.NO_VOICE_FOR_LANGUAGE -> "this phone has no voice for this language"
    NotPlayedReason.TEXT_TO_SPEECH_FAILED -> "text-to-speech did not work"
    NotPlayedReason.PLAYBACK_FAILED -> "the phone could not play the sound"
    NotPlayedReason.TIMEOUT -> "it did not finish within 20 s"
    NotPlayedReason.BUSY -> "another question was still playing"
    else -> reason
}

/** "14:02:31", the same clock time the hub prints for the check. */
internal fun clockTime(epochMs: Long, zone: ZoneId): String =
    CLOCK_TIME.format(Instant.ofEpochMilli(epochMs).atZone(zone))

/** "1.8 s". Not String.format: in Italian that would print "1,8". */
internal fun tenthsOfSeconds(ms: Long): String {
    val tenths = ms.coerceAtLeast(0) / 100
    return "${tenths / 10}.${tenths % 10} s"
}

private val CLOCK_TIME = DateTimeFormatter.ofPattern("HH:mm:ss")

// The level is drawn under this line (MicLevelChart), so the line no longer gives it as a number.
private fun micStatus(mic: MicState): String = when (mic) {
    is MicState.Recording -> "Listening · ${formatDuration(mic.secondsRecorded)} recorded"
    MicState.Paused -> "Paused: the microphone and the light sensor are off"
    is MicState.Problem -> "Microphone problem: ${mic.message}. Trying again…"
}

private fun lightStatus(light: LightStatus): String = when (light) {
    LightStatus.Waiting -> "Light: waiting for the sensor…"
    LightStatus.NoSensor -> "Light: this phone has no light sensor"
    is LightStatus.Reading -> "Light: ${light.state.wire} · ${light.lux} lux"
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
