package app.nonnawatch.listener.voice

import java.io.File
import java.io.IOException
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull

/** How playing the check-in question went; the hub gets it in `ask_played`. */
sealed interface AskResult {
    /** Both times are this phone's clock, like the audio frames' `capture_ms`. */
    data class Played(val startedMs: Long, val endedMs: Long) : AskResult

    /** [reason] is one of [NotPlayedReason]. */
    data class NotPlayed(val reason: String) : AskResult
}

/**
 * Why a question did not play, as sent to the hub. The hub prints it and alerts the family at
 * once, so these are short printable ASCII.
 */
object NotPlayedReason {
    /** The alarm volume is at zero, or Do Not Disturb is set to total silence. */
    const val NO_AUDIO_OUTPUT = "no_audio_output"

    /** The phone has no text-to-speech, or it would not start. */
    const val NO_TEXT_TO_SPEECH = "no_text_to_speech"

    /** Text-to-speech has no voice for the question's language. */
    const val NO_VOICE_FOR_LANGUAGE = "no_voice_for_language"

    /** Text-to-speech started but did not make the speech. */
    const val TEXT_TO_SPEECH_FAILED = "text_to_speech_failed"

    /** The phone could not play the sound. */
    const val PLAYBACK_FAILED = "playback_failed"

    /** It had not finished after 20 s, when the hub gives up waiting anyway. */
    const val TIMEOUT = "timeout"

    /** Another question was still playing. The hub promises one at a time, so this should not happen. */
    const val BUSY = "busy"
}

/** The last check-in question the hub asked for, for the screen. */
sealed interface QuestionState {
    data object Playing : QuestionState

    data class Finished(val result: AskResult) : QuestionState
}

/**
 * The phone's side of the hub's voice check (docs/api-contract.md, "Voice check, end to end").
 * [app.nonnawatch.listener.hub.HubLink] calls it; [CheckInQuestion] is the real one.
 */
interface VoiceCheck {
    /** Plays the question and returns once it has ended, or why it could not play. */
    suspend fun ask(text: String, lang: String): AskResult

    /** The family's recording, to play instead of [ask]'s text from now on. */
    suspend fun saveClip(audio: ByteArray)

    /** The family deleted their recording: speak the text again. */
    suspend fun deleteClip()
}

/** Turns the question's text into speech, written to a sound file. */
fun interface Speech {
    /** Writes [text], spoken in [lang] (like `it-IT`), into [into]. Null when done, else a [NotPlayedReason]. */
    suspend fun write(text: String, lang: String, into: File): String?
}

/** Plays a sound file as an alarm, so it is heard when the phone is on silent. */
fun interface AlarmPlayer {
    /** Returns once the sound has ended. Cancelling stops the sound. */
    suspend fun play(file: File): AskResult
}

/**
 * Plays the check-in question: the family's recording if there is one, otherwise the hub's text
 * spoken by the phone. The microphone keeps streaming meanwhile; the hub ignores the question
 * itself, which may contain "bene" or "aiuto", using the times in [AskResult.Played].
 *
 * The phone's voice goes into [speechFile] and is played from there, not spoken straight out:
 * text-to-speech plays its sound in the voice app, and Android 17 may silence that while this
 * app is in the background. Played from this app, the sound counts as part of the listening
 * service that the person started. The file is deleted after each question.
 */
class CheckInQuestion(
    private val clips: ClipStore,
    private val speech: Speech,
    private val player: AlarmPlayer,
    private val alarmAudible: () -> Boolean,
    private val speechFile: File,
    private val io: CoroutineDispatcher = Dispatchers.IO,
    private val log: (String) -> Unit = {},
) : VoiceCheck {

    private val _state = MutableStateFlow<QuestionState?>(null)

    /** The last question the hub asked for; tests from the screen do not count. */
    val state: StateFlow<QuestionState?> = _state.asStateFlow()

    override suspend fun ask(text: String, lang: String): AskResult {
        _state.value = QuestionState.Playing
        var result: AskResult? = null
        try {
            return play(text, lang, useClip = true).also { result = it }
        } finally {
            // Cancelled (stopped listening, or the hub connection was lost): nothing to show.
            _state.value = result?.let { QuestionState.Finished(it) }
        }
    }

    /** The Test button: always the phone's own voice, to check that it can speak [lang]. */
    suspend fun test(text: String, lang: String): AskResult = play(text, lang, useClip = false)

    override suspend fun saveClip(audio: ByteArray) = withContext(io) {
        try {
            clips.save(audio)
            log("Saved the family's recorded question")
        } catch (e: IOException) {
            log("Could not save the family's recorded question: ${e.message}")
        }
    }

    override suspend fun deleteClip() = withContext(io) {
        clips.delete()
        log("The family deleted their recorded question")
    }

    // The hub stops waiting for ask_played after 20 s, so a question that has not ended by then
    // has failed anyway. The timeout also stops a voice app that never answers.
    private suspend fun play(text: String, lang: String, useClip: Boolean): AskResult =
        withTimeoutOrNull(PLAY_TIMEOUT_MS) { playNow(text, lang, useClip) }
            ?: AskResult.NotPlayed(NotPlayedReason.TIMEOUT)

    private suspend fun playNow(text: String, lang: String, useClip: Boolean): AskResult {
        // Played anyway, nobody would hear it; saying so lets the hub alert the family at once.
        if (!alarmAudible()) return AskResult.NotPlayed(NotPlayedReason.NO_AUDIO_OUTPUT)

        val clip = if (useClip) withContext(io) { clips.current() } else null
        if (clip != null) {
            when (val played = player.play(clip)) {
                is AskResult.Played -> return played
                is AskResult.NotPlayed ->
                    log("The family's recording did not play (${played.reason}); speaking the question instead")
            }
        }

        try {
            speech.write(text, lang, speechFile)?.let { problem -> return AskResult.NotPlayed(problem) }
            return player.play(speechFile)
        } finally {
            speechFile.delete()
        }
    }
}

private const val PLAY_TIMEOUT_MS = 20_000L
