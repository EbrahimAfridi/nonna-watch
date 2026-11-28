package app.nonnawatch.listener

import app.nonnawatch.core.Room
import app.nonnawatch.core.protocol.LightState
import app.nonnawatch.listener.hub.LinkState
import app.nonnawatch.listener.light.LightStatus
import app.nonnawatch.listener.settings.ListenerSettings
import app.nonnawatch.listener.settings.SettingsStore
import app.nonnawatch.listener.voice.AskResult
import app.nonnawatch.listener.voice.NotPlayedReason
import app.nonnawatch.listener.voice.QuestionLanguage
import app.nonnawatch.listener.voice.QuestionState
import java.time.ZoneOffset
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class ListenerViewModelTest {

    /** Stands in for the real service: records what was asked, and the test sets its state. */
    private class FakeControl : ListenerControl {
        override val state = MutableStateFlow<ServiceState>(ServiceState.Stopped())
        var startCalls = 0
        var stopCalls = 0
        val pauseCalls = mutableListOf<Boolean>()

        override fun start() {
            startCalls += 1
        }

        override fun stop() {
            stopCalls += 1
        }

        override fun setPaused(paused: Boolean) {
            pauseCalls += paused
        }

        val tested = mutableListOf<QuestionLanguage>()
        val testResult = CompletableDeferred<AskResult>()

        override suspend fun testQuestion(language: QuestionLanguage): AskResult {
            tested += language
            return testResult.await()
        }
    }

    private class FakeSettings(var saved: ListenerSettings = ListenerSettings()) : SettingsStore {
        override fun load() = saved

        override fun save(settings: ListenerSettings) {
            saved = settings
        }

        override fun deviceId() = "test-device"
    }

    private val control = FakeControl()
    private val settings = FakeSettings()
    private val ready = ListenerSettings("ws://10.0.2.2:8000/ws/listener", "secret", Room.KITCHEN)

    // UTC, so the clock times in these tests do not depend on this PC's time zone.
    private fun viewModel() = ListenerViewModel(control, settings, zone = ZoneOffset.UTC)

    private fun running(
        mic: MicState = MicState.Recording(secondsRecorded = 42, levels = listOf(0.25f, 0.75f)),
        hub: LinkState = LinkState.Connected("ebrahim-mac", secondsSent = 40),
        room: Room = Room.HALLWAY,
        question: QuestionState? = null,
        light: LightStatus? = null,
    ) = ServiceState.Running(room, mic, hub, question, light)

    // viewModelScope runs on Android's main thread; in a PC test a test dispatcher stands in.
    @Before
    fun useTestMainThread() {
        Dispatchers.setMain(UnconfinedTestDispatcher())
    }

    @After
    fun restoreMainThread() {
        Dispatchers.resetMain()
    }

    @Test
    fun itStartsNotListeningWithTheSavedSettings() {
        settings.saved = ready.copy(room = Room.BEDROOM)

        val viewModel = viewModel()

        assertEquals("ws://10.0.2.2:8000/ws/listener", viewModel.hubUrl)
        assertEquals("secret", viewModel.token)
        val state = viewModel.state.value
        assertEquals(Room.BEDROOM, state.room)
        assertFalse(state.listening)
        assertEquals("Not listening", state.status)
        assertEquals("", state.hubStatus)
    }

    @Test
    fun everyChangeIsSavedAtOnce() {
        val viewModel = viewModel()

        viewModel.editHubUrl("ws://192.168.43.12:8000/ws/listener")
        viewModel.editToken("abc")
        viewModel.selectRoom(Room.BATHROOM)

        assertEquals(
            ListenerSettings("ws://192.168.43.12:8000/ws/listener", "abc", Room.BATHROOM),
            settings.saved,
        )
    }

    @Test
    fun startingNeedsTheAddressAndTheToken() {
        val viewModel = viewModel()

        assertFalse(viewModel.readyToStart())
        assertEquals(
            "Not listening: enter the hub address the hub printed, like ws://192.168.43.12:8000/ws/listener",
            viewModel.state.value.status,
        )

        viewModel.editHubUrl("ws://10.0.2.2:8000/ws/listener")
        assertEquals("Not listening", viewModel.state.value.status) // typing clears the message
        assertFalse(viewModel.readyToStart())
        assertEquals(
            "Not listening: enter the token (HUB_TOKEN in the hub's .env file)",
            viewModel.state.value.status,
        )

        viewModel.editToken("secret")
        assertTrue(viewModel.readyToStart())
        assertEquals(0, control.startCalls) // the screen asks for the microphone first
    }

    @Test
    fun startAsksTheServiceToStart() {
        settings.saved = ready
        val viewModel = viewModel()

        viewModel.start()

        assertEquals(1, control.startCalls)
    }

    @Test
    fun itShowsTheMicrophoneAndTheHub() {
        val viewModel = viewModel()
        control.state.value = running()

        val state = viewModel.state.value
        assertTrue(state.listening)
        assertEquals(Room.HALLWAY, state.room)
        assertEquals("Listening · 42 s recorded", state.status)
        assertEquals(listOf(0.25f, 0.75f), state.micLevels) // drawn under the status line
        assertEquals("Hub: connected to ebrahim-mac · 40 s sent", state.hubStatus)
    }

    @Test
    fun theLevelDrawingShowsOnlyWhileTheMicrophoneRecords() {
        val viewModel = viewModel()
        assertNull(viewModel.state.value.micLevels) // not listening

        control.state.value = running(mic = MicState.Recording(secondsRecorded = 0))
        assertEquals(emptyList<Float>(), viewModel.state.value.micLevels) // an empty box until the first second

        control.state.value = running(mic = MicState.Paused)
        assertNull(viewModel.state.value.micLevels)

        control.state.value = running(mic = MicState.Problem("the microphone stopped working"))
        assertNull(viewModel.state.value.micLevels)
    }

    @Test
    fun itShowsTheLightSensor() {
        val viewModel = viewModel()
        assertEquals("", viewModel.state.value.lightStatus) // not listening

        control.state.value = running(light = LightStatus.Waiting)
        assertEquals("Light: waiting for the sensor…", viewModel.state.value.lightStatus)

        control.state.value = running(light = LightStatus.Reading(LightState.BRIGHT, lux = 112))
        assertEquals("Light: bright · 112 lux", viewModel.state.value.lightStatus)

        control.state.value = running(light = LightStatus.Reading(LightState.DARK, lux = 3))
        assertEquals("Light: dark · 3 lux", viewModel.state.value.lightStatus)

        control.state.value = running(light = LightStatus.NoSensor)
        assertEquals("Light: this phone has no light sensor", viewModel.state.value.lightStatus)

        control.state.value = running(mic = MicState.Paused, light = null) // pause turns the sensor off
        assertEquals("", viewModel.state.value.lightStatus)
    }

    @Test
    fun itShowsWhenTheHubCannotBeReached() {
        val viewModel = viewModel()

        control.state.value = running(hub = LinkState.Connecting)
        assertEquals("Hub: connecting…", viewModel.state.value.hubStatus)

        control.state.value = running(hub = LinkState.Waiting("hub not reachable", retryInSeconds = 8))
        assertEquals("Hub: hub not reachable. Trying again in 8 s", viewModel.state.value.hubStatus)
    }

    @Test
    fun settingsCannotChangeWhileListening() {
        settings.saved = ready
        val viewModel = viewModel()
        control.state.value = running(room = Room.KITCHEN)

        viewModel.selectRoom(Room.BEDROOM)
        viewModel.editHubUrl("ws://elsewhere:8000/ws/listener")
        viewModel.editToken("other")

        assertEquals(Room.KITCHEN, viewModel.state.value.room)
        assertEquals("ws://10.0.2.2:8000/ws/listener", viewModel.hubUrl)
        assertEquals("secret", viewModel.token)
        assertEquals(ready, settings.saved)
    }

    @Test
    fun startingTwiceDoesNotStartTwice() {
        settings.saved = ready
        val viewModel = viewModel()
        control.state.value = running()

        assertFalse(viewModel.readyToStart())
        viewModel.start()

        assertEquals(0, control.startCalls)
    }

    @Test
    fun pauseAndResume() {
        val viewModel = viewModel()
        control.state.value = running()

        viewModel.togglePause()
        control.state.value = running(mic = MicState.Paused)
        assertTrue(viewModel.state.value.paused)
        assertEquals("Paused: the microphone and the light sensor are off", viewModel.state.value.status)
        viewModel.togglePause()

        assertEquals(listOf(true, false), control.pauseCalls)
    }

    @Test
    fun pauseDoesNothingWhileNotListening() {
        viewModel().togglePause()
        assertEquals(emptyList<Boolean>(), control.pauseCalls)
    }

    @Test
    fun stopAsksTheServiceToStop() {
        val viewModel = viewModel()
        viewModel.stop()
        assertEquals(1, control.stopCalls)
    }

    @Test
    fun aMicrophoneProblemIsShownAndStopStaysAvailable() {
        val viewModel = viewModel()
        control.state.value = running(mic = MicState.Problem("the microphone stopped working"))

        val state = viewModel.state.value
        assertTrue(state.listening)
        assertEquals("Microphone problem: the microphone stopped working. Trying again…", state.status)
    }

    @Test
    fun whenTheServiceStoppedByItselfTheScreenSaysWhy() {
        val viewModel = viewModel()
        control.state.value = ServiceState.Stopped("the hub refused the token")

        assertEquals("Not listening: the hub refused the token", viewModel.state.value.status)
    }

    @Test
    fun aDeniedPermissionSaysWhatToDoUntilTheNextTry() {
        settings.saved = ready
        val viewModel = viewModel()

        viewModel.micPermissionDenied()
        assertEquals(MIC_PERMISSION_DENIED, viewModel.state.value.status)

        viewModel.start()
        assertEquals("Not listening", viewModel.state.value.status)
    }

    @Test
    fun itShowsTheLastCheckInQuestion() {
        val viewModel = viewModel()

        control.state.value = running()
        assertEquals("", viewModel.state.value.questionStatus) // the hub has not asked yet

        control.state.value = running(question = QuestionState.Playing)
        assertEquals("Check-in question: playing…", viewModel.state.value.questionStatus)

        control.state.value = running(
            question = QuestionState.Finished(
                AskResult.Played(startedMs = 1_795_698_192_400L, endedMs = 1_795_698_195_900L),
            ),
        )
        assertEquals("Check-in question: played at 13:03:15", viewModel.state.value.questionStatus)

        control.state.value = running(
            question = QuestionState.Finished(AskResult.NotPlayed(NotPlayedReason.NO_AUDIO_OUTPUT)),
        )
        assertEquals(
            "Check-in question: not played, the alarm volume is at zero, or Do Not Disturb is on total silence",
            viewModel.state.value.questionStatus,
        )
    }

    @Test
    fun theTestSpeaksInTheChosenLanguageAndSaysWhatWentWrong() {
        val viewModel = viewModel()

        viewModel.selectTestLanguage(QuestionLanguage.URDU)
        viewModel.testQuestion()
        assertEquals(listOf(QuestionLanguage.URDU), control.tested)
        assertTrue(viewModel.state.value.testing)
        assertEquals("Test (Urdu): playing…", viewModel.state.value.testStatus)

        viewModel.testQuestion() // a second tap while it plays
        viewModel.selectTestLanguage(QuestionLanguage.ITALIAN)
        assertEquals(1, control.tested.size)
        assertEquals(QuestionLanguage.URDU, viewModel.state.value.testLanguage)

        control.testResult.complete(AskResult.NotPlayed(NotPlayedReason.NO_VOICE_FOR_LANGUAGE))
        assertFalse(viewModel.state.value.testing)
        assertEquals(
            "Test (Urdu): not played, this phone has no voice for this language",
            viewModel.state.value.testStatus,
        )
    }

    @Test
    fun aTestThatPlayedSaysHowLongItTook() {
        val viewModel = viewModel()
        control.testResult.complete(AskResult.Played(startedMs = 1_000, endedMs = 2_850))

        viewModel.testQuestion() // works without listening and without a hub

        assertEquals(listOf(QuestionLanguage.ITALIAN), control.tested)
        assertEquals("Test (Italian): played, 1.8 s", viewModel.state.value.testStatus)
    }

    @Test
    fun choosingAnotherLanguageClearsTheLastTest() {
        val viewModel = viewModel()
        control.testResult.complete(AskResult.Played(startedMs = 1_000, endedMs = 2_850))
        viewModel.testQuestion()

        viewModel.selectTestLanguage(QuestionLanguage.HINDI)

        assertEquals("", viewModel.state.value.testStatus)
    }

    @Test
    fun secondsWithATenthReadTheSameInEveryLanguage() {
        assertEquals("0.0 s", tenthsOfSeconds(0))
        assertEquals("1.8 s", tenthsOfSeconds(1_850))
        assertEquals("12.0 s", tenthsOfSeconds(12_000))
        assertEquals("0.0 s", tenthsOfSeconds(-5)) // a clock that stepped back
    }

    @Test
    fun durationsReadLikeAPerson() {
        assertEquals("0 s", formatDuration(0))
        assertEquals("59 s", formatDuration(59))
        assertEquals("1 min 0 s", formatDuration(60))
        assertEquals("3 min 5 s", formatDuration(185))
        assertEquals("1 h 0 min", formatDuration(3_600))
        assertEquals("1 h 2 min", formatDuration(3_725))
    }
}
