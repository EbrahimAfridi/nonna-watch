"""C5: learn Maria's usual day from history, and spot when today is different.

This file is PURE LOGIC: no database, no network, no clock. Everything comes in as plain Python
values (events as dicts, `now` as a datetime) and findings come out. That is what lets the same code
run inside Ebrahim's hub (Path B), in a Cloud Function (Path A), and in tests with a fake clock.
`checks.py` does the Firestore reading and writing around it.

The three checks (requirements, "Detection rules"):

  routine_missing   A room she is normally in every morning has no sounds yet, well past the usual
                    time. Example: no kitchen sounds by 09:15 when breakfast is normally by 08:45.
  long_silence      No sound at all in the house for 45 minutes, at an hour she is usually active.
  hub_offline       The hub itself stopped sending heartbeats. (A silent listener PHONE is detected by
                    the hub, which holds every phone's connection: decision D29. Only the cloud can
                    notice the hub dying, so that is the one offline check here.)

Habits are learned per category (the hub's water, cooking, door, ...), not per raw YAMNet label,
because one habit can show up under several labels ("Water tap, faucet", "Sink"). See events.py.

How "usual" is learned, in plain words:
  For every room (and every room+category) we look at the last 14 days and note, for each hour of the
  day, on what share of days something happened then (`hourShare`), and what time the first sound
  of the day usually is (`usualFirstMinute`, the median) and how late it gets on a normal late day
  (`latestFirstMinute`, the 90th percentile). Weekends with a lie-in are therefore "normal".
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from statistics import median
from zoneinfo import ZoneInfo

from nonna_cloud.defaults import DEFAULT_SETTINGS
from nonna_cloud.events import category_of

ALL = "*"

# Categories that can happen with nobody there (a TV left on), so they don't prove she is up and about.
PASSIVE_CATEGORIES = {"tv_music"}


# ------------------------------------------------------------------ data shapes

@dataclass
class Routine:
    """One learned habit. room == ALL means the whole house; category == ALL means anything in the room."""
    room: str
    category: str
    hourShare: list[float]
    usualFirstMinute: int | None
    latestFirstMinute: int | None
    daysObserved: int

    @property
    def id(self) -> str:
        return routine_id(self.room, self.category)

    def to_doc(self) -> dict:
        return {
            "room": self.room, "category": self.category, "hourShare": self.hourShare,
            "usualFirstMinute": self.usualFirstMinute, "latestFirstMinute": self.latestFirstMinute,
            "daysObserved": self.daysObserved,
        }

    @classmethod
    def from_doc(cls, d: dict) -> "Routine":
        return cls(d["room"], d["category"], list(d["hourShare"]), d.get("usualFirstMinute"),
                   d.get("latestFirstMinute"), d["daysObserved"])


@dataclass
class Finding:
    """Something the family may need to hear about. `checks.py` turns it into an alert document."""
    type: str               # routine_missing / long_silence / hub_offline
    room: str
    time: datetime          # when the problem started (deadline passed, last sound, last heartbeat)
    message: str            # the text the family reads
    alert_id: str           # stable id, so the same problem is reported only once
    voice_check: bool       # ask "Are you okay?" first (requirements: yes for routine and silence)
    severity: str = "alert"
    detail: dict = field(default_factory=dict)


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def routine_id(room: str, category: str) -> str:
    if room == ALL:
        return "_activity"
    return f"{room}__{'all' if category == ALL else slug(category)}"


def is_activity(e: dict) -> bool:
    return category_of(e) not in PASSIVE_CATEGORIES


def settings_for(home: dict) -> dict:
    """Defaults, overridden by the home's own settings, adjusted for visitor mode."""
    s = {**DEFAULT_SETTINGS, **(home.get("settings") or {})}
    if home.get("mode") == "visitor":           # someone else is around: be more patient
        s["longSilenceMinutes"] *= 2
        s["routineGraceMinutes"] *= 2
    return s


def hhmm(minute_of_day: float) -> str:
    m = int(minute_of_day) % (24 * 60)
    return f"{m // 60:02d}:{m % 60:02d}"


def room_name(room: str) -> str:
    return room.replace("_", " ")


# ------------------------------------------------------------------ learning

def _hours_covered(start: datetime, end: datetime, tz: ZoneInfo) -> set[tuple[date, int]]:
    """Every (local day, local hour) an event touches. A 2-hour TV session counts for 2-3 hours."""
    out = set()
    t = start.astimezone(tz).replace(minute=0, second=0, microsecond=0)
    end_local = end.astimezone(tz)
    while t <= end_local:
        out.add((t.date(), t.hour))
        t += timedelta(hours=1)
    return out


def _percentile(values: list[int], p: float) -> int:
    s = sorted(values)
    return s[max(0, math.ceil(p * len(s)) - 1)]


def learn(events: list[dict], tz: ZoneInfo, min_share: float = 0.6) -> dict[str, Routine]:
    """Learn routines from past events. Returns {routine id: Routine}.

    Days with no events at all are left out (the system was probably off), so a broken hub
    for a day doesn't teach the learner that "nothing happens on Tuesdays".
    """
    days = {e["start"].astimezone(tz).date() for e in events}
    n = len(days)
    if n == 0:
        return {}

    hits: dict[tuple[str, str], set[tuple[date, int]]] = {}
    firsts: dict[tuple[str, str], dict[date, int]] = {}

    def add(key: tuple[str, str], e: dict) -> None:
        hits.setdefault(key, set()).update(_hours_covered(e["start"], e["end"], tz))
        local = e["start"].astimezone(tz)
        minute = local.hour * 60 + local.minute
        day_firsts = firsts.setdefault(key, {})
        day_firsts[local.date()] = min(minute, day_firsts.get(local.date(), minute))

    for e in events:
        add((e["room"], category_of(e)), e)        # every category, for the app to show
        if is_activity(e):
            add((e["room"], ALL), e)               # "someone is in the kitchen"
            add((ALL, ALL), e)                     # "someone is in the house"

    routines = {}
    for (room, category), covered in hits.items():
        share = [round(sum(1 for (_, h) in covered if h == hour) / n, 3) for hour in range(24)]
        first = list(firsts[(room, category)].values())
        regular = len(first) / n >= min_share
        r = Routine(
            room=room, category=category, hourShare=share,
            usualFirstMinute=int(median(first)) if regular else None,
            latestFirstMinute=_percentile(first, 0.9) if regular else None,
            daysObserved=n,
        )
        routines[r.id] = r
    return routines


# ------------------------------------------------------------------ checks

def check_missing_routines(routines: dict[str, Routine], events: list[dict], now: datetime,
                           tz: ZoneInfo, s: dict, name: str) -> list[Finding]:
    """Rooms with a regular first-sound-of-the-day time that are still silent well past it."""
    local_now = now.astimezone(tz)
    midnight = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    minute_now = local_now.hour * 60 + local_now.minute
    out = []
    for r in routines.values():
        if r.room == ALL or r.category != ALL or r.latestFirstMinute is None:
            continue
        deadline = r.latestFirstMinute + s["routineGraceMinutes"]
        if deadline >= 24 * 60 or minute_now < deadline:
            continue
        seen_today = any(e["room"] == r.room and is_activity(e) and midnight <= e["start"] <= now
                         for e in events)
        if seen_today:
            continue
        out.append(Finding(
            type="routine_missing", room=r.room,
            time=midnight + timedelta(minutes=deadline),
            message=(f"No {room_name(r.room)} sounds yet today. "
                     f"{name} is usually in the {room_name(r.room)} by {hhmm(r.usualFirstMinute)}."),
            alert_id=f"routine_missing_{r.room}_{local_now.date().isoformat()}",
            voice_check=True,
            detail={"routine": r.id, "usual": hhmm(r.usualFirstMinute), "deadline": hhmm(deadline)},
        ))
    return out


def check_long_silence(activity: Routine | None, events: list[dict], now: datetime, tz: ZoneInfo,
                       s: dict, name: str) -> Finding | None:
    """No activity sound anywhere for `longSilenceMinutes`, during hours that are usually active."""
    if activity is None:
        return None
    limit = timedelta(minutes=s["longSilenceMinutes"])
    acts = [e for e in events if is_activity(e) and e["start"] <= now]
    if any(e["end"] >= now for e in acts):
        return None                                        # something is happening right now
    last = max((e["end"] for e in acts), default=None)
    if last is not None and now - last < limit:
        return None

    # Every hour inside the silent window must be one where she is usually active.
    t, hours = now - limit, set()
    while t <= now:
        hours.add(t.astimezone(tz).hour)
        t += timedelta(minutes=15)
    if any(activity.hourShare[h] < s["routineMinShare"] for h in hours):
        return None

    local_now = now.astimezone(tz)
    if last is None:
        since, minutes = "today", None
        alert_id = f"long_silence_{local_now.date().isoformat()}"
        start = now - limit
    else:
        since = hhmm(last.astimezone(tz).hour * 60 + last.astimezone(tz).minute)
        minutes = int((now - last).total_seconds() // 60)
        alert_id = f"long_silence_{int(last.timestamp() * 1000)}"
        start = last
    return Finding(
        type="long_silence", room="", time=start,
        message=(f"The house has been silent for {minutes} minutes (since {since}), "
                 if minutes is not None else "The house has been silent all day, ")
                + f"at a time {name} is usually active.",
        alert_id=alert_id, voice_check=True,
        detail={"silentMinutes": minutes, "limitMinutes": s["longSilenceMinutes"]},
    )


def check_hub_offline(devices: dict[str, dict], now: datetime, tz: ZoneInfo, s: dict) -> list[Finding]:
    """The hub stopped writing its heartbeat (devices/hub).

    The hub writes every `heartbeatMinutes` (5, D7), so its heartbeat can legitimately be almost 5
    minutes old. It counts as offline after `offlineMinutes + heartbeatMinutes` (10 by default).
    This only means something when the check runs in the cloud (Path A): a hub can't notice its own death.
    """
    limit = timedelta(minutes=s["offlineMinutes"] + s["heartbeatMinutes"])
    out = []
    for dev_id, d in sorted(devices.items()):
        last = d.get("lastHeartbeat")
        if d.get("kind") != "hub" or last is None or now - last < limit:
            continue
        at = hhmm(last.astimezone(tz).hour * 60 + last.astimezone(tz).minute)
        out.append(Finding(
            type="hub_offline", room="", time=last,
            message=f"The home hub has been offline since {at}. Instant alerts can't be sent until it is back.",
            alert_id=f"hub_offline_{dev_id}_{int(last.timestamp() * 1000)}",
            voice_check=False, detail={"deviceId": dev_id},
        ))
    return out


def run_checks(home: dict, routines: dict[str, Routine], events: list[dict],
               devices: dict[str, dict], now: datetime) -> list[Finding]:
    """All checks for one home at time `now`. `events` (see events.py) should cover the last 24 hours."""
    tz = ZoneInfo(home.get("timezone", "Europe/Rome"))
    s = settings_for(home)
    name = home.get("name", "She")
    findings = check_hub_offline(devices, now, tz, s)

    if home.get("mode") == "away":
        return findings                                  # nobody home: only watch the equipment
    activity = routines.get("_activity")
    if activity is None or activity.daysObserved < s["routineMinDays"]:
        return findings                                  # not enough history to know what's normal yet

    findings += check_missing_routines(routines, events, now, tz, s, name)
    silence = check_long_silence(activity, events, now, tz, s, name)
    if silence:
        findings.append(silence)
    return findings
