package app.nonnawatch.listener

import app.nonnawatch.core.Room
import app.nonnawatch.listener.hub.LinkState
import app.nonnawatch.listener.settings.ListenerSettings
import app.nonnawatch.listener.settings.SettingsStore
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
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

    private fun viewModel() = ListenerViewModel(control, settings)

    private fun running(
        mic: MicState = MicState.Recording(secondsRecorded = 42, levelPercent = 7),
        hub: LinkState = LinkState.Connected("ebrahim-mac", secondsSent = 40),
        room: Room = Room.HALLWAY,
    ) = ServiceState.Running(room, mic, hub)

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
        assertEquals("Listening · 42 s recorded · level 7 %", state.status)
        assertEquals("Hub: connected to ebrahim-mac · 40 s sent", state.hubStatus)
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
        assertEquals("Paused: the microphone is off", viewModel.state.value.status)
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
    fun durationsReadLikeAPerson() {
        assertEquals("0 s", formatDuration(0))
        assertEquals("59 s", formatDuration(59))
        assertEquals("1 min 0 s", formatDuration(60))
        assertEquals("3 min 5 s", formatDuration(185))
        assertEquals("1 h 0 min", formatDuration(3_600))
        assertEquals("1 h 2 min", formatDuration(3_725))
    }
}
