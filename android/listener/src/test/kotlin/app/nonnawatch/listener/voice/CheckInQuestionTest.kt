package app.nonnawatch.listener.voice

import java.io.File
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.async
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

/**
 * Which sound the question plays and what the hub is told, with a fake voice and a fake player.
 * Time is simulated, so the 20 s limit takes no real time.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class CheckInQuestionTest {
    @get:Rule
    val folder = TemporaryFolder()

    private val spoken = mutableListOf<Pair<String, String>>()
    private val played = mutableListOf<ByteArray>()
    private var speechProblem: String? = null
    private var audible = true

    /** When set, the player plays until this completes, like a real one. */
    private var playing: CompletableDeferred<Unit>? = null

    /** What the player answers for the family's recording and for the phone's voice. */
    private var clipResult: AskResult = AskResult.Played(startedMs = 1_000, endedMs = 2_500)
    private var speechResult: AskResult = AskResult.Played(startedMs = 1_000, endedMs = 2_500)

    private val speechFile by lazy { File(folder.root, "question.wav") }
    private val clipDir by lazy { File(folder.root, "voice_check") }

    private fun TestScope.question(clips: ClipStore = ClipStore(clipDir)) = CheckInQuestion(
        clips = clips,
        speech = { text, lang, into ->
            spoken += text to lang
            if (speechProblem == null) into.writeBytes(SPEECH)
            speechProblem
        },
        player = { file ->
            played += file.readBytes()
            playing?.await()
            if (file == speechFile) speechResult else clipResult
        },
        alarmAudible = { audible },
        speechFile = speechFile,
        io = StandardTestDispatcher(testScheduler),
    )

    @Test
    fun withoutARecordingThePhoneSpeaksTheText() = runTest {
        val result = question().ask("Mamma, stai bene?", "it-IT")

        assertEquals(AskResult.Played(startedMs = 1_000, endedMs = 2_500), result)
        assertEquals(listOf("Mamma, stai bene?" to "it-IT"), spoken)
        assertArrayEquals(SPEECH, played.single())
        assertFalse(speechFile.exists()) // the phone's voice is not kept
    }

    @Test
    fun theFamilysRecordingPlaysInsteadOfTheText() = runTest {
        val question = question()
        question.saveClip(CLIP)

        question.ask("Mamma, stai bene?", "it-IT")

        assertTrue(spoken.isEmpty())
        assertArrayEquals(CLIP, played.single())
    }

    @Test
    fun ifTheRecordingWillNotPlayThePhoneSpeaksTheTextInstead() = runTest {
        val question = question()
        question.saveClip(CLIP)
        clipResult = AskResult.NotPlayed(NotPlayedReason.PLAYBACK_FAILED)

        val result = question.ask("Mamma, stai bene?", "it-IT")

        assertEquals(AskResult.Played(startedMs = 1_000, endedMs = 2_500), result)
        assertEquals(2, played.size)
        assertArrayEquals(SPEECH, played.last())
    }

    @Test
    fun afterTheFamilyDeletesTheRecordingThePhoneSpeaksAgain() = runTest {
        val question = question()
        question.saveClip(CLIP)

        question.deleteClip()
        question.ask("Mamma, stai bene?", "it-IT")

        assertArrayEquals(SPEECH, played.single())
    }

    @Test
    fun aSilentAlarmIsReportedInsteadOfPlayingToNobody() = runTest {
        audible = false

        val result = question().ask("Mamma, stai bene?", "it-IT")

        assertEquals(AskResult.NotPlayed("no_audio_output"), result)
        assertTrue(played.isEmpty())
    }

    @Test
    fun aMissingVoiceIsReported() = runTest {
        speechProblem = NotPlayedReason.NO_VOICE_FOR_LANGUAGE

        val result = question().ask("کیا آپ ٹھیک ہیں؟", "ur-PK")

        assertEquals(AskResult.NotPlayed("no_voice_for_language"), result)
        assertTrue(played.isEmpty())
    }

    @Test
    fun aQuestionThatNeverEndsGivesUpAfterTwentySeconds() = runTest {
        playing = CompletableDeferred() // never completes
        val result = async { question().ask("Mamma, stai bene?", "it-IT") }

        advanceTimeBy(19_999)
        runCurrent()
        assertFalse(result.isCompleted)

        advanceTimeBy(1)
        runCurrent()
        assertEquals(AskResult.NotPlayed("timeout"), result.await())
        assertFalse(speechFile.exists())
    }

    @Test
    fun theScreenSeesTheQuestionPlayingAndThenHowItWent() = runTest {
        val question = question()
        playing = CompletableDeferred()
        assertNull(question.state.value)

        val asking = async { question.ask("Mamma, stai bene?", "it-IT") }
        runCurrent()
        assertEquals(QuestionState.Playing, question.state.value)

        playing?.complete(Unit)
        asking.await()
        assertEquals(
            QuestionState.Finished(AskResult.Played(startedMs = 1_000, endedMs = 2_500)),
            question.state.value,
        )
    }

    @Test
    fun aStoppedQuestionLeavesNothingBehind() = runTest {
        val question = question()
        playing = CompletableDeferred()
        val asking = async { question.ask("Mamma, stai bene?", "it-IT") }
        runCurrent()

        asking.cancel()
        runCurrent()

        assertNull(question.state.value)
        assertFalse(speechFile.exists())
    }

    @Test
    fun theTestUsesThePhonesVoiceEvenWithARecordingAndIsNotShownAsAHubQuestion() = runTest {
        val question = question()
        question.saveClip(CLIP)

        question.test("Jesi li dobro?", "bs-BA")

        assertEquals(listOf("Jesi li dobro?" to "bs-BA"), spoken)
        assertArrayEquals(SPEECH, played.single())
        assertNull(question.state.value)
    }

    @Test
    fun aRecordingThatCannotBeSavedDoesNotStopTheLink() = runTest {
        val notAFolder = folder.newFile("not-a-folder") // the store's folder cannot be made here

        question(ClipStore(notAFolder)).saveClip(CLIP) // no exception
    }

    private companion object {
        val SPEECH = byteArrayOf(1, 2, 3)
        val CLIP = byteArrayOf(9, 9, 9, 9)
    }
}
