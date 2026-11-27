package app.nonnawatch.listener

import app.nonnawatch.core.Room
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
        val started = mutableListOf<Room>()
        var stopCalls = 0

        override fun start(room: Room) {
            started += room
        }

        override fun stop() {
            stopCalls += 1
        }
    }

    private val control = FakeControl()

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
    fun startsInKitchenNotListening() {
        val state = ListenerViewModel(control).state.value
        assertEquals(Room.KITCHEN, state.room)
        assertFalse(state.listening)
        assertEquals("Not listening", state.status)
    }

    @Test
    fun selectRoomUpdatesState() {
        val viewModel = ListenerViewModel(control)
        viewModel.selectRoom(Room.BEDROOM)
        assertEquals(Room.BEDROOM, viewModel.state.value.room)
    }

    @Test
    fun startAsksTheServiceToListenInTheChosenRoom() {
        val viewModel = ListenerViewModel(control)
        viewModel.selectRoom(Room.BATHROOM)
        viewModel.start()
        assertEquals(listOf(Room.BATHROOM), control.started)
    }

    @Test
    fun showsWhatTheServiceIsDoing() {
        val viewModel = ListenerViewModel(control)
        control.state.value = ServiceState.Listening(Room.HALLWAY, secondsRecorded = 42, levelPercent = 7)

        val state = viewModel.state.value
        assertTrue(state.listening)
        assertEquals(Room.HALLWAY, state.room)
        assertEquals("Listening · 42 s recorded · level 7 %", state.status)
    }

    @Test
    fun theRoomCannotChangeWhileListening() {
        val viewModel = ListenerViewModel(control)
        control.state.value = ServiceState.Listening(Room.KITCHEN, secondsRecorded = 1, levelPercent = 0)

        viewModel.selectRoom(Room.BEDROOM)

        assertEquals(Room.KITCHEN, viewModel.state.value.room)
    }

    @Test
    fun startingTwiceDoesNotStartTwice() {
        val viewModel = ListenerViewModel(control)
        control.state.value = ServiceState.Listening(Room.KITCHEN, secondsRecorded = 1, levelPercent = 0)

        viewModel.start()

        assertEquals(emptyList<Room>(), control.started)
    }

    @Test
    fun stopAsksTheServiceToStop() {
        val viewModel = ListenerViewModel(control)
        viewModel.stop()
        assertEquals(1, control.stopCalls)
    }

    @Test
    fun aMicrophoneProblemIsShownAndStopStaysAvailable() {
        val viewModel = ListenerViewModel(control)
        control.state.value = ServiceState.MicProblem(Room.KITCHEN, "the microphone stopped working")

        val state = viewModel.state.value
        assertTrue(state.listening)
        assertEquals("Microphone problem: the microphone stopped working. Trying again…", state.status)
    }

    @Test
    fun whenTheServiceStoppedByItselfTheScreenSaysWhy() {
        val viewModel = ListenerViewModel(control)
        control.state.value = ServiceState.Stopped("the microphone permission is missing")

        assertEquals(
            "Not listening: the microphone permission is missing",
            viewModel.state.value.status,
        )
    }

    @Test
    fun aDeniedPermissionSaysWhatToDoUntilTheNextTry() {
        val viewModel = ListenerViewModel(control)

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
