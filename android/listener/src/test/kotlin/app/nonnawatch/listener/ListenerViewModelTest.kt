package app.nonnawatch.listener

import app.nonnawatch.core.Room
import org.junit.Assert.assertEquals
import org.junit.Test

class ListenerViewModelTest {
    @Test
    fun startsInKitchenNotListening() {
        val state = ListenerViewModel().state.value
        assertEquals(Room.KITCHEN, state.room)
        assertEquals("Not listening", state.status)
    }

    @Test
    fun selectRoomUpdatesState() {
        val viewModel = ListenerViewModel()
        viewModel.selectRoom(Room.BEDROOM)
        assertEquals(Room.BEDROOM, viewModel.state.value.room)
    }
}
