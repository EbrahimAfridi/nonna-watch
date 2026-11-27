"""Tests for the fake-history generator (C4). No database needed: `uv run pytest`."""

from datetime import date, timedelta
from zoneinfo import ZoneInfo

from nonna_cloud.seed import generate
from nonna_cloud.timeline import chunk_id, flatten, to_chunks

# The hub's 19 categories (hub/nonna_hub/categories.py).
HUB_CATEGORIES = {"scream", "distress", "thud", "glass", "smoke_alarm", "speech", "cough", "snoring",
                  "footsteps", "door", "doorbell", "phone", "alarm", "water", "toilet", "cooking",
                  "cleaning", "grooming", "tv_music"}

TZ = ZoneInfo("Europe/Rome")
TODAY = date(2026, 11, 26)          # a Thursday


def local_days(events):
    return {e["start"].astimezone(TZ).date() for e in events}


def test_covers_the_days_before_today_and_leaves_today_empty():
    events = generate(14, today=TODAY)
    days = local_days(events)
    assert min(days) == TODAY - timedelta(days=14)
    assert max(days) == TODAY - timedelta(days=1)
    assert TODAY not in days


def test_same_seed_gives_same_history():
    assert generate(3, today=TODAY, seed=1) == generate(3, today=TODAY, seed=1)
    assert generate(3, today=TODAY, seed=1) != generate(3, today=TODAY, seed=2)


def test_events_use_the_hub_categories():
    for e in generate(14, today=TODAY):
        assert set(e) == {"room", "category", "label", "confidence", "start", "end"}
        assert e["category"] in HUB_CATEGORIES
        assert e["room"] in {"kitchen", "bathroom", "bedroom"}
        assert 0 <= e["confidence"] <= 1
        assert e["end"] >= e["start"]
        assert e["start"].tzinfo is not None


def test_chunks_hold_every_event_exactly_once():
    events = generate(14, today=TODAY)
    chunks = to_chunks(events, source="seed")
    assert sorted(flatten(chunks), key=lambda e: (e["start"], e["room"], e["label"])) ==         sorted(events, key=lambda e: (e["start"], e["room"], e["label"]))


def test_chunks_follow_the_schema():
    for c in to_chunks(generate(3, today=TODAY), source="seed"):
        assert set(c) == {"room", "deviceId", "source", "flushedAt", "start", "end", "events"}
        assert c["source"] == "seed" and c["deviceId"] == f"listener-{c['room']}"
        assert c["start"] == min(e["start"] for e in c["events"])
        assert c["end"] == max(e["end"] for e in c["events"])
        assert all(e["end"] < c["flushedAt"] for e in c["events"])     # flushed after they ended
        assert c["flushedAt"].timestamp() % 60 == 0                     # on a minute boundary


def test_chunk_ids_are_unique_so_nothing_is_overwritten():
    for offset in range(0, 365, 7):
        chunks = to_chunks(generate(14, today=TODAY + timedelta(days=offset)), source="seed")
        assert len({chunk_id(c) for c in chunks}) == len(chunks)


def test_size_stays_far_inside_the_free_write_quota():
    writes_per_day = len(to_chunks(generate(14, today=TODAY), source="seed")) / 14
    assert 10 <= writes_per_day <= 60


def test_breakfast_in_the_kitchen_almost_every_morning():
    """The routine demo ("no kitchen sounds by 11:00") only works if history shows it's normal."""
    events = generate(14, today=TODAY)
    mornings = {
        e["start"].astimezone(TZ).date()
        for e in events
        if e["room"] == "kitchen" and e["start"].astimezone(TZ).hour < 10
    }
    assert len(mornings) >= 12


def test_nothing_happens_in_the_middle_of_the_night():
    for e in generate(14, today=TODAY):
        assert not 1 <= e["start"].astimezone(TZ).hour < 6


def test_today_can_be_filled_with_one_room_left_silent():
    from datetime import datetime
    from nonna_cloud.seed import generate_today
    events = generate_today("10:30", ["kitchen"], today=TODAY)
    cutoff = datetime(2026, 11, 26, 10, 30, tzinfo=TZ)
    assert events, "the morning should not be empty"
    assert all(e["room"] != "kitchen" for e in events)
    assert all(e["end"] <= cutoff for e in events)
    assert all(e["start"].astimezone(TZ).date() == TODAY for e in events)
