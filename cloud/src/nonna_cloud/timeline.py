"""How events are packed into Firestore (decision D20), and unpacked again.

Firestore counts every document written as one write, and the free plan allows 20,000 a day. So the
hub does not write one document per sound. Every 60 seconds (10 s during the demo) it writes ONE
document per room, holding every event in that room that ended since the last write: a "chunk".

    homes/{homeId}/timeline/{room}_{flushedAtEpochMillis}
    {
      "room": "kitchen", "deviceId": "listener-kitchen", "source": "hub",
      "flushedAt": <Timestamp>,
      "start": <earliest event start>, "end": <latest event end>,    # lets queries pick chunks by time
      "events": [
        {"category": "water", "label": "Water tap, faucet", "confidence": 0.91,
         "start": <Timestamp>, "end": <Timestamp>},
        ...
      ]
    }

That caps the timeline at 1,440 writes per room per day (one a minute), however busy the room is.

Inside this package an event is a flat dict: {room, category, label, confidence, start, end}.
`to_chunks` packs a list of them; `flatten` unpacks chunk documents back into that list.
"""

from __future__ import annotations

from datetime import datetime

# YAMNet label -> hub category, for the labels the seed script uses. The full list is the hub's
# hub/nonna_hub/categories.py; these names must match it.
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
    "Speech": "speech",
    "Snoring": "snoring",
    "Walk, footsteps": "footsteps",
}

EVENT_KEYS = ("category", "label", "confidence", "start", "end")


def device_id(room: str) -> str:
    return f"listener-{room}"


def chunk_id(chunk: dict) -> str:
    """{room}_{flushedAtEpochMillis}. One room is flushed at most once per instant, and a retry from
    the hub's offline queue reuses the same flushedAt, so it overwrites instead of duplicating."""
    return f"{chunk['room']}_{int(chunk['flushedAt'].timestamp() * 1000)}"


def to_chunks(events: list[dict], source: str, flush_seconds: int = 60) -> list[dict]:
    """Pack events the way the hub does: per room, one chunk per flush, holding the events that ended
    before that flush. Used by the seed script to produce realistic history."""
    by_key: dict[tuple[str, datetime], list[dict]] = {}
    for e in events:
        end = e["end"]
        # The flush that picks this event up is the next multiple of flush_seconds after it ended.
        epoch = end.timestamp()
        flushed = datetime.fromtimestamp((int(epoch // flush_seconds) + 1) * flush_seconds, tz=end.tzinfo)
        by_key.setdefault((e["room"], flushed), []).append(e)

    chunks = []
    for (room, flushed), evs in sorted(by_key.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        evs = sorted(evs, key=lambda e: e["start"])
        chunks.append({
            "room": room,
            "deviceId": device_id(room),
            "source": source,
            "flushedAt": flushed,
            "start": min(e["start"] for e in evs),
            "end": max(e["end"] for e in evs),
            "events": [{k: e[k] for k in EVENT_KEYS} for e in evs],
        })
    return chunks


def flatten(chunks: list[dict]) -> list[dict]:
    """Chunk documents -> flat events, each with its room, sorted by start."""
    out = [{"room": c["room"], **e} for c in chunks for e in c.get("events", [])]
    out.sort(key=lambda e: e["start"])
    return out


def overlaps(e: dict, since: datetime, until: datetime | None = None) -> bool:
    return e["end"] >= since and (until is None or e["start"] < until)

