package app.nonnawatch.core

/**
 * The fixed room ids from docs/api-contract.md. The protocol sends [id]; apps show [label].
 * Adding a room means changing the contract first, so the hub accepts it.
 */
enum class Room(val id: String, val label: String) {
    KITCHEN("kitchen", "Kitchen"),
    BATHROOM("bathroom", "Bathroom"),
    BEDROOM("bedroom", "Bedroom"),
    LIVING_ROOM("living_room", "Living room"),
    HALLWAY("hallway", "Hallway");

    companion object {
        fun fromId(id: String): Room? = entries.firstOrNull { it.id == id }
    }
}
