package app.nonnawatch.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class RoomTest {
    @Test
    fun idsMatchTheContract() {
        assertEquals(
            listOf("kitchen", "bathroom", "bedroom", "living_room", "hallway"),
            Room.entries.map { it.id },
        )
    }

    @Test
    fun fromIdFindsKnownRoomsOnly() {
        assertEquals(Room.LIVING_ROOM, Room.fromId("living_room"))
        assertNull(Room.fromId("garage"))
    }
}
