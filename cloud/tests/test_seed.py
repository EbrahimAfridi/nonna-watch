"""Tests for the fake-history generator (C4). No database needed: `uv run pytest`."""

from datetime import date, timedelta
from zoneinfo import ZoneInfo

from nonna_cloud.seed import event_id, generate

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


def test_events_follow_the_schema():
    for e in generate(14, today=TODAY):
        assert set(e) == {"room", "deviceId", "sound", "confidence", "start", "end", "source"}
        assert e["source"] == "seed"
        assert e["room"] in {"kitchen", "bathroom", "bedroom"}
        assert e["deviceId"] == f"listener-{e['room']}"
        assert 0 <= e["confidence"] <= 1
        assert e["end"] >= e["start"]
        assert e["start"].tzinfo is not None


def test_ids_are_unique_so_nothing_is_overwritten():
    # Checked for every start date in a year: one date once produced two events in the same second.
    for offset in range(365):
        events = generate(14, today=TODAY + timedelta(days=offset))
        assert len({event_id(e) for e in events}) == len(events), TODAY + timedelta(days=offset)


def test_size_stays_far_inside_the_free_write_quota():
    per_day = len(generate(14, today=TODAY)) / 14
    assert 20 <= per_day <= 60


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
