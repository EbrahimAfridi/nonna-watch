"""C5: learn Maria's usual day from history, and spot when today is different.

This file is PURE LOGIC: no database, no network, no clock. Everything comes in as plain Python
values (events as dicts, `now` as a datetime) and findings come out. That is what lets the same code
run inside Ebrahim's hub (Path B), in a Cloud Function (Path A), and in tests with a fake clock.
`checks.py` does the Firestore reading and writing around it.

The three checks (requirements, "Detection rules"):

  routine_missing   A room she is normally in every morning has no sounds yet, well past the usual
                    time. Example: no kitchen sounds by 09:15 when breakfast is normally by 08:45.
  long_silence      No sound at all in the house for 45 minutes, at an hour she is usually active.
  listener_offline  A listener phone stopped sending heartbeats. hub_offline: the hub itself did.

How "usual" is learned, in plain words:
  For every room (and every room+sound) we look at the last 14 days and note, for each hour of the
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

ALL = "*"

# Sounds that can happen with nobody there (a TV left on), so they don't prove she is up and about.
PASSIVE_SOUNDS = {"Silence", "Television", "Radio", "Music"}


# ------------------------------------------------------------------ data shapes

@dataclass
class Routine:
    """One learned habit. room == ALL means the whole house; sound == ALL means any sound in the room."""
    room: str
    sound: str
    hourShare: list[float]
    usualFirstMinute: int | None
    latestFirstMinute: int | None
    daysObserved: int

    @property
    def id(self) -> str:
        return routine_id(self.room, self.sound)

    def to_doc(self) -> dict:
        return {
            "room": self.room, "sound": self.sound, "hourShare": self.hourShare,
            "usualFirstMinute": self.usualFirstMinute, "latestFirstMinute": self.latestFirstMinute,
            "daysObserved": self.daysObserved,
        }

    @classmethod
    def from_doc(cls, d: dict) -> "Routine":
        return cls(d["room"], d["sound"], list(d["hourShare"]), d.get("usualFirstMinute"),
                   d.get("latestFirstMinute"), d["daysObserved"])


@dataclass
class Finding:
    """Something the family may need to hear about. `checks.py` turns it into an alert document."""
    type: str               # routine_missing / long_silence / listener_offline / hub_offline
    room: str
    time: datetime          # when the problem started (deadline passed, last sound, last heartbeat)
    message: str            # the text the family reads
    alert_id: str           # stable id, so the same problem is reported only once
    voice_check: bool       # ask "Are you okay?" first (requirements: yes for routine and silence)
    severity: str = "alert"
    detail: dict = field(default_factory=dict)


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def routine_id(room: str, sound: str) -> str:
    if room == ALL:
        return "_activity"
    return f"{room}__{'all' if sound == ALL else slug(sound)}"


def is_activity(e: dict) -> bool:
    return e["sound"] not in PASSIVE_SOUNDS


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
        add((e["room"], e["sound"]), e)            # every sound, for the app to show
        if is_activity(e):
            add((e["room"], ALL), e)               # "someone is in the kitchen"
            add((ALL, ALL), e)                     # "someone is in the house"

    routines = {}
    for (room, sound), covered in hits.items():
        share = [round(sum(1 for (_, h) in covered if h == hour) / n, 3) for hour in range(24)]
        first = list(firsts[(room, sound)].values())
        regular = len(first) / n >= min_share
        r = Routine(
            room=room, sound=sound, hourShare=share,
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
        if r.room == ALL or r.sound != ALL or r.latestFirstMinute is None:
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


def check_offline(devices: dict[str, dict], now: datetime, tz: ZoneInfo, s: dict) -> list[Finding]:
    """Listeners (and the hub) whose heartbeat stopped.

    The hub writes heartbeats every `heartbeatMinutes` (5, see D7), so a heartbeat can legitimately be
    almost 5 minutes old. Rules:
      - a listener the hub marked offline (online == false) -> alert after `offlineMinutes`
        (the hub writes that at once when the phone disconnects, so "unplug -> alert in 5 min" holds);
      - anything not heard from for `offlineMinutes + heartbeatMinutes` -> alert (catches a dead hub,
        which can't write online == false itself).
    If the hub is offline, its listeners look offline too; only the hub is reported then.
    """
    limit = timedelta(minutes=s["offlineMinutes"])
    slack = timedelta(minutes=s["heartbeatMinutes"])

    def down(d: dict) -> bool:
        last = d.get("lastHeartbeat")
        if last is None:
            return False
        age = now - last
        return age >= limit + slack or (d.get("online") is False and age >= limit)

    hub_down = any(d.get("kind") == "hub" and down(d) for d in devices.values())
    out = []
    for dev_id, d in sorted(devices.items()):
        if not down(d) or (hub_down and d.get("kind") != "hub"):
            continue
        last = d["lastHeartbeat"]
        at = hhmm(last.astimezone(tz).hour * 60 + last.astimezone(tz).minute)
        if d.get("kind") == "hub":
            kind, room = "hub_offline", ""
            msg = f"The home hub has been offline since {at}. Instant alerts can't be sent until it is back."
        else:
            kind, room = "listener_offline", d.get("room", "")
            msg = f"{room_name(room).capitalize() or 'A'} listener offline since {at}."
        out.append(Finding(type=kind, room=room, time=last, message=msg,
                           alert_id=f"{kind}_{dev_id}_{int(last.timestamp() * 1000)}",
                           voice_check=False, detail={"deviceId": dev_id}))
    return out


def run_checks(home: dict, routines: dict[str, Routine], events: list[dict],
               devices: dict[str, dict], now: datetime) -> list[Finding]:
    """All checks for one home at time `now`. `events` should cover at least the last 24 hours."""
    tz = ZoneInfo(home.get("timezone", "Europe/Rome"))
    s = settings_for(home)
    name = home.get("name", "She")
    findings = check_offline(devices, now, tz, s)

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
