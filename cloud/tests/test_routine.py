"""Tests for the routine learner and checks (C5). Pure logic, fake clock, no database."""

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from nonna_cloud.defaults import DEFAULT_SETTINGS, demo_home
from nonna_cloud.routine import (
    check_hub_offline, check_long_silence, check_missing_routines, learn, run_checks, settings_for,
)
from nonna_cloud.seed import generate
from nonna_cloud.events import CATEGORY_OF

TZ = ZoneInfo("Europe/Rome")
TODAY = date(2026, 11, 26)               # a Thursday
S = {**DEFAULT_SETTINGS}


def at(hh: int, mm: int = 0, day: date = TODAY) -> datetime:
    return datetime(day.year, day.month, day.day, hh, mm, tzinfo=TZ)


def ev(room: str, sound: str, start: datetime, minutes: float = 2) -> dict:
    """An event document (D30) for a YAMNet label, with the hub's category for it."""
    return {"room": room, "deviceId": f"listener-{room}", "sound": sound, "category": CATEGORY_OF[sound],
            "confidence": 0.9, "start": start, "end": start + timedelta(minutes=minutes), "source": "test"}


@pytest.fixture(scope="module")
def routines():
    return learn(generate(14, today=TODAY), TZ)


@pytest.fixture
def home():
    return demo_home(["luca@gmail.com"])


# ------------------------------------------------------------------ learning

def test_learns_from_every_day_of_history(routines):
    assert routines["_activity"].daysObserved == 14


def test_breakfast_time_is_learned(routines):
    k = routines["kitchen__all"]
    assert 7 * 60 + 45 <= k.usualFirstMinute <= 8 * 60 + 45        # around 08:05-08:30
    assert k.usualFirstMinute <= k.latestFirstMinute <= 10 * 60     # weekend lie-ins included


def test_night_is_quiet_and_mornings_are_busy(routines):
    share = routines["_activity"].hourShare
    assert share[3] == 0
    assert share[8] >= 0.9


def test_tv_does_not_count_as_her_being_active():
    events = [ev("kitchen", "Television", at(9, 0, TODAY - timedelta(days=d)), 60) for d in range(1, 8)]
    r = learn(events, TZ)
    assert "kitchen__tv_music" in r            # still learned, so the app can show it
    assert "kitchen__all" not in r             # but it proves nothing about Maria
    assert "_activity" not in r


def test_events_without_a_category_still_work():
    """D30 lists room, sound, confidence, start, end; if the hub leaves category out, use the label."""
    events = [ev("kitchen", "Water tap, faucet", at(8, 0, TODAY - timedelta(days=d))) for d in range(1, 8)]
    for e in events:
        del e["category"]
    r = learn(events, TZ)
    assert "kitchen__water" in r and r["kitchen__all"].daysObserved == 7
    tv = ev("kitchen", "Television", at(9, 0))
    del tv["category"]
    assert "_activity" not in learn([tv], TZ)      # a TV is still not a sign of life


def test_days_without_any_data_are_not_counted():
    events = [ev("kitchen", "Water tap, faucet", at(8, 0, TODAY - timedelta(days=d))) for d in (1, 2, 5)]
    assert learn(events, TZ)["kitchen__all"].daysObserved == 3


# ------------------------------------------------------------------ routine missing

def test_no_kitchen_by_late_morning_is_reported(routines):
    today = [ev("bathroom", "Toilet flush", at(7, 45))]
    found = check_missing_routines(routines, today, at(10, 30), TZ, S, "Maria")
    kitchen = [f for f in found if f.room == "kitchen"]
    assert len(kitchen) == 1
    assert kitchen[0].voice_check is True                      # ask "Are you okay?" first
    assert "kitchen" in kitchen[0].message
    assert kitchen[0].alert_id == "routine_missing_kitchen_2026-11-26"


def test_not_reported_before_the_deadline(routines):
    assert check_missing_routines(routines, [], at(7, 0), TZ, S, "Maria") == []


def test_not_reported_if_she_was_in_the_kitchen(routines):
    today = [ev("kitchen", "Water tap, faucet", at(8, 10)), ev("bathroom", "Toilet flush", at(7, 45)),
             ev("bedroom", "Door", at(7, 40))]
    assert check_missing_routines(routines, today, at(10, 30), TZ, S, "Maria") == []


def test_tv_alone_in_the_kitchen_still_counts_as_missing(routines):
    today = [ev("kitchen", "Television", at(8, 0), 120)]
    found = check_missing_routines(routines, today, at(10, 30), TZ, S, "Maria")
    assert any(f.room == "kitchen" for f in found)


def test_same_problem_gets_the_same_id_all_day(routines):
    a = check_missing_routines(routines, [], at(10, 30), TZ, S, "Maria")
    b = check_missing_routines(routines, [], at(13, 0), TZ, S, "Maria")
    assert {f.alert_id for f in a} <= {f.alert_id for f in b}


# ------------------------------------------------------------------ long silence

def test_long_silence_at_an_active_time(routines):
    # Around lunch she is active every day, so 52 silent minutes then is unusual.
    recent = [ev("kitchen", "Dishes, pots, and pans", at(12, 5), 3)]
    f = check_long_silence(routines["_activity"], recent, at(13, 0), TZ, S, "Maria")
    assert f is not None
    assert f.type == "long_silence" and f.voice_check is True
    assert "52 minutes" in f.message and "12:08" in f.message


def test_silence_during_her_usual_tv_time_is_normal(routines):
    # Mid-morning she mostly watches TV, which doesn't count as activity, so silence then is normal.
    recent = [ev("kitchen", "Dishes, pots, and pans", at(9, 0), 3)]
    assert check_long_silence(routines["_activity"], recent, at(9, 55), TZ, S, "Maria") is None


def test_short_silence_is_fine(routines):
    recent = [ev("kitchen", "Dishes, pots, and pans", at(12, 5), 3)]
    assert check_long_silence(routines["_activity"], recent, at(12, 30), TZ, S, "Maria") is None


def test_silence_at_night_is_normal(routines):
    recent = [ev("bedroom", "Door", at(23, 0, TODAY - timedelta(days=1)), 0.1)]
    assert check_long_silence(routines["_activity"], recent, at(3, 0), TZ, S, "Maria") is None


def test_something_happening_right_now_is_not_silence(routines):
    recent = [ev("kitchen", "Water tap, faucet", at(12, 0), 120)]   # still running at 13:00
    assert check_long_silence(routines["_activity"], recent, at(13, 0), TZ, S, "Maria") is None


def test_a_tv_left_on_does_not_hide_silence(routines):
    recent = [ev("kitchen", "Dishes, pots, and pans", at(12, 5), 3),
              ev("kitchen", "Television", at(12, 10), 120)]
    assert check_long_silence(routines["_activity"], recent, at(13, 0), TZ, S, "Maria") is not None


def test_one_silence_is_reported_once(routines):
    recent = [ev("kitchen", "Dishes, pots, and pans", at(12, 5), 3)]
    a = check_long_silence(routines["_activity"], recent, at(13, 0), TZ, S, "Maria")
    b = check_long_silence(routines["_activity"], recent, at(13, 15), TZ, S, "Maria")
    assert a.alert_id == b.alert_id


# ------------------------------------------------------------------ hub offline
# (A silent listener phone is the hub's job, decision D29. The cloud watches the hub itself.)

def hub(minutes_ago: float, now: datetime) -> dict:
    return {"hub": {"kind": "hub", "room": "", "online": True,
                    "lastHeartbeat": (now - timedelta(minutes=minutes_ago)).astimezone(timezone.utc)}}


def test_hub_heartbeat_a_few_minutes_old_is_normal():
    now = at(14, 10)
    assert check_hub_offline(hub(9, now), now, TZ, S) == []        # writes every 5 min, so up to ~5 is normal


def test_silent_hub_is_reported():
    now = at(14, 10)
    found = check_hub_offline(hub(11, now), now, TZ, S)
    assert [f.type for f in found] == ["hub_offline"]
    assert "since 13:59" in found[0].message
    assert found[0].voice_check is False


def test_listener_phones_are_left_to_the_hub():
    now = at(14, 10)
    devs = {"listener-kitchen": {"kind": "listener", "room": "kitchen", "online": False,
                                 "lastHeartbeat": (now - timedelta(hours=1)).astimezone(timezone.utc)}}
    assert check_hub_offline(devs, now, TZ, S) == []


def test_one_hub_outage_is_reported_once():
    now = at(14, 10)
    devs = hub(11, now)
    later = now + timedelta(minutes=15)
    devs_later = {"hub": devs["hub"]}                                # same last heartbeat
    assert check_hub_offline(devs, now, TZ, S)[0].alert_id == check_hub_offline(devs_later, later, TZ, S)[0].alert_id


# ------------------------------------------------------------------ everything together

def test_away_mode_only_watches_equipment(routines, home):
    home["mode"] = "away"
    assert run_checks(home, routines, [], {}, at(12, 0)) == []


def test_no_routine_checks_without_enough_history(home):
    short = learn(generate(3, today=TODAY), TZ)
    assert run_checks(home, short, [], {}, at(12, 0)) == []


def test_visitor_mode_is_more_patient(home):
    home["mode"] = "visitor"
    s = settings_for(home)
    assert s["longSilenceMinutes"] == 2 * DEFAULT_SETTINGS["longSilenceMinutes"]


def test_family_settings_override_defaults(home):
    home["settings"]["longSilenceMinutes"] = 60
    assert settings_for(home)["longSilenceMinutes"] == 60


def test_demo_scenario_m6(routines, home):
    """M6: history seeded, today she got up and used the bathroom, but at 10:30 still no kitchen."""
    today = [ev("bedroom", "Door", at(7, 40), 0.1), ev("bathroom", "Toilet flush", at(7, 41)),
             ev("bathroom", "Water tap, faucet", at(7, 43)), ev("bedroom", "Walk, footsteps", at(10, 0))]
    found = run_checks(home, routines, today, {}, at(10, 30))
    assert [(f.type, f.room) for f in found] == [("routine_missing", "kitchen")]
