"""What one sound event looks like in Firestore (decision D30), and small helpers around it.

The hub writes ONE document per event, when the event ends:

    homes/{homeId}/events/{deviceId}_{startEpochMillis}
    {
      "room": "kitchen", "deviceId": "listener-kitchen",
      "sound": "Water tap, faucet",      # YAMNet label at the peak (D30)
      "category": "water",               # the hub's household category (optional, see below)
      "confidence": 0.91,
      "start": <Timestamp>, "end": <Timestamp>,
      "source": "hub"                    # hub / cloud / phone / seed
    }

`category` is one of the hub's 19 categories (hub/nonna_hub/categories.py). The routine learner
prefers it, because one habit shows up under several YAMNet labels ("Water tap, faucet", "Sink").
If an event has no category, `category_of` falls back to the label, so nothing breaks.

The document id is {deviceId}_{startEpochMillis}: a retry from the hub's offline queue overwrites
the same document instead of adding a duplicate.
"""

from __future__ import annotations

# YAMNet label -> hub category, for the labels the seed script uses. Must match hub/nonna_hub/categories.py.
CATEGORY_OF = {
    "Door": "door",
    "Toilet flush": "toilet",
    "Water tap, faucet": "water",
    "Microwave oven": "cooking",
    "Dishes, pots, and pans": "cooking",
    "Cutlery, silverware": "cooking",
    "Chopping (food)": "cooking",
    "Frying (food)": "cooking",
    "Television": "tv_music",
    "Radio": "tv_music",
    "Music": "tv_music",
    "Speech": "speech",
    "Snoring": "snoring",
    "Walk, footsteps": "footsteps",
}


def device_id(room: str) -> str:
    return f"listener-{room}"


def event_id(e: dict) -> str:
    """{deviceId}_{startEpochMillis}, as in docs/firestore-schema.md."""
    return f"{e['deviceId']}_{int(e['start'].timestamp() * 1000)}"


def category_of(e: dict) -> str:
    """The event's category; if the writer left it out, the hub's category for its label, else the label."""
    return e.get("category") or CATEGORY_OF.get(e["sound"], e["sound"])
