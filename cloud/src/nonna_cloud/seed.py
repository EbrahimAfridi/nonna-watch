"""C4: write realistic fake history for a home, so the routine layer has something to learn from.

Maria's usual day (times shift a little every day, and some things don't happen every day):
wake ~07:40 (later on weekends) -> bathroom -> breakfast in the kitchen -> morning TV ->
lunch ~12:30 -> nap in the bedroom -> afternoon TV -> dinner ~19:15 -> evening TV -> bed ~22:45.
On Sundays a visitor comes for lunch (lots of "Speech" in the kitchen).

Usage (from the cloud/ folder):

    uv run python -m nonna_cloud.seed --emulator --member you@gmail.com       # local emulator
    uv run python -m nonna_cloud.seed --member you@gmail.com                   # real project
    uv run python -m nonna_cloud.seed --dry-run                                # just print a summary

Options: --home maria   --days 14   --clear (delete old seed events first)   --seed 42 (same fake
history every time)   --with-devices (also write listener heartbeats)   --telegram-chat-id ...

Demo of a broken routine (M6): also fill TODAY up to a time, leaving one room silent:

    uv run python -m nonna_cloud.seed --clear --today-until 10:30 --skip-room kitchen
    uv run python -m nonna_cloud.checks --now 10:30            # -> "No kitchen sounds yet today"

Events are packed the way the hub packs them (decision D20, see timeline.py): one document per room
per 60-second flush, in homes/{home}/timeline. Maria's fake events are spread out, so most minutes hold
just one: 14 days is about 400 writes (free quota: 20,000 per day). A real, busy room saves far more. Chunks from this script have
source == "seed", so --clear only ever deletes fake data.
"""

from __future__ import annotations

import argparse
import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from nonna_cloud.defaults import demo_home
from nonna_cloud.timeline import CATEGORY_OF, chunk_id, device_id, to_chunks


@dataclass(frozen=True)
class Step:
    """One thing Maria usually does. `at` is minutes after an anchor (wake-up, lunch, ...)."""
    at: float          # minutes after the anchor
    room: str
    sound: str         # YAMNet display name
    minutes: float     # typical duration
    p: float = 1.0     # chance it happens on a given day


# Anchors: (name, usual time in minutes after midnight, +- jitter in minutes)
WAKE = ("wake", 7 * 60 + 40, 15)
LUNCH = ("lunch", 12 * 60 + 30, 15)
NAP = ("nap", 14 * 60, 15)
AFTERNOON = ("afternoon", 15 * 60 + 40, 15)
DINNER = ("dinner", 19 * 60 + 15, 20)
BED = ("bed", 22 * 60 + 45, 20)

DAY_PLAN: list[tuple[tuple[str, int, int], list[Step]]] = [
    (WAKE, [
        Step(0, "bedroom", "Door", 0.1),
        Step(1, "bathroom", "Toilet flush", 0.3),
        Step(3, "bathroom", "Water tap, faucet", 2),
        Step(25, "kitchen", "Water tap, faucet", 1),
        Step(27, "kitchen", "Microwave oven", 2, p=0.8),
        Step(31, "kitchen", "Dishes, pots, and pans", 3),
        Step(50, "kitchen", "Television", 70, p=0.7),
        Step(170, "bathroom", "Water tap, faucet", 1, p=0.5),
        Step(185, "kitchen", "Speech", 10, p=0.3),            # a phone call
    ]),
    (LUNCH, [
        Step(-30, "kitchen", "Chopping (food)", 4, p=0.7),
        Step(-20, "kitchen", "Frying (food)", 10, p=0.6),
        Step(0, "kitchen", "Cutlery, silverware", 15),
        Step(20, "kitchen", "Water tap, faucet", 5),
        Step(22, "kitchen", "Dishes, pots, and pans", 6),
    ]),
    (NAP, [
        Step(0, "bedroom", "Door", 0.1),
        Step(20, "bedroom", "Snoring", 40, p=0.6),
        Step(85, "bedroom", "Door", 0.1),
    ]),
    (AFTERNOON, [
        Step(0, "kitchen", "Television", 90, p=0.8),
        Step(110, "bathroom", "Toilet flush", 0.3, p=0.7),
        Step(112, "bathroom", "Water tap, faucet", 1, p=0.7),
    ]),
    (DINNER, [
        Step(0, "kitchen", "Water tap, faucet", 2),
        Step(3, "kitchen", "Microwave oven", 3, p=0.7),
        Step(10, "kitchen", "Cutlery, silverware", 15),
        Step(30, "kitchen", "Dishes, pots, and pans", 5),
        Step(45, "kitchen", "Television", 100, p=0.9),
    ]),
    (BED, [
        Step(0, "bathroom", "Water tap, faucet", 3),
        Step(4, "bathroom", "Toilet flush", 0.3),
        Step(10, "bedroom", "Door", 0.1),
    ]),
]

SUNDAY_VISIT = [Step(m, "kitchen", "Speech", 12, p=0.9) for m in (-40, -10, 25, 60, 95)]


def generate_day(day: date, tz: ZoneInfo, rng: random.Random) -> list[dict]:
    """All fake events for one local calendar day, sorted by start time."""
    midnight = datetime(day.year, day.month, day.day, tzinfo=tz)
    weekend = day.weekday() >= 5
    events: list[dict] = []

    for (name, usual, jitter), steps in DAY_PLAN:
        anchor = usual + rng.uniform(-jitter, jitter)
        if name == "wake" and weekend:
            anchor += 40                                  # sleeps in at the weekend
        plan = steps + (SUNDAY_VISIT if name == "lunch" and day.weekday() == 6 else [])
        for s in plan:
            if rng.random() > s.p:
                continue
            start_min = anchor + s.at + rng.uniform(-3, 3)
            dur_s = max(2.0, s.minutes * 60 * rng.uniform(0.7, 1.3))
            start = midnight + timedelta(minutes=start_min)
            events.append(_event(s.room, s.sound, start, start + timedelta(seconds=dur_s), rng))

    # A few footsteps in the kitchen during the day.
    for _ in range(rng.randint(3, 6)):
        start = midnight + timedelta(minutes=rng.uniform(8 * 60 + 30, 21 * 60))
        events.append(_event("kitchen", "Walk, footsteps", start, start + timedelta(seconds=rng.uniform(3, 15)), rng))

    events.sort(key=lambda e: e["start"])
    return events


def _event(room: str, label: str, start: datetime, end: datetime, rng: random.Random) -> dict:
    # Rounded to whole seconds. Stored in UTC; Firestore keeps the instant, the app shows local time.
    start = start.astimezone(timezone.utc).replace(microsecond=0)
    end = max(end.astimezone(timezone.utc).replace(microsecond=0), start)
    return {
        "room": room,
        "category": CATEGORY_OF[label],
        "label": label,
        "confidence": round(rng.uniform(0.45, 0.95), 2),
        "start": start,
        "end": end,
    }


def generate(days: int, tz_name: str = "Europe/Rome", today: date | None = None, seed: int | None = 42) -> list[dict]:
    """The last `days` full days before `today` (today itself is left empty, so the demo can break it)."""
    tz = ZoneInfo(tz_name)
    today = today or datetime.now(tz).date()
    rng = random.Random(seed)
    out: list[dict] = []
    for i in range(days, 0, -1):
        out.extend(generate_day(today - timedelta(days=i), tz, rng))
    return out


def generate_today(until: str, skip_rooms: list[str], tz_name: str = "Europe/Rome",
                   today: date | None = None, seed: int | None = 7) -> list[dict]:
    """Today's normal events up to `until` ("HH:MM"), minus the rooms in `skip_rooms`."""
    tz = ZoneInfo(tz_name)
    today = today or datetime.now(tz).date()
    hh, mm = (int(x) for x in until.split(":"))
    cutoff = datetime(today.year, today.month, today.day, hh, mm, tzinfo=tz).astimezone(timezone.utc)
    out = []
    for e in generate_day(today, tz, random.Random(seed)):
        if e["room"] in skip_rooms or e["start"] >= cutoff:
            continue
        e["end"] = min(e["end"], cutoff)
        out.append(e)
    return out


# ---------------------------------------------------------------- Firestore part

def clear_seed_events(db, home_id: str) -> int:
    events = db.collection("homes").document(home_id).collection("timeline")
    n = 0
    while True:
        from google.cloud.firestore_v1.base_query import FieldFilter
        docs = list(events.where(filter=FieldFilter("source", "==", "seed")).limit(400).stream())
        if not docs:
            return n
        batch = db.batch()
        for d in docs:
            batch.delete(d.reference)
        batch.commit()
        n += len(docs)


def write(db, home_id: str, events: list[dict], members: list[str], telegram_chat_id: str,
          with_devices: bool) -> None:
    from google.cloud import firestore

    home_ref = db.collection("homes").document(home_id)
    snap = home_ref.get()
    if not snap.exists:
        home_ref.set(demo_home(members, telegram_chat_id))
        print(f"Created home '{home_id}'.")
    else:
        update = {}
        if members:
            update["memberEmails"] = firestore.ArrayUnion([m.strip().lower() for m in members])
        if telegram_chat_id:
            update["telegramChatId"] = telegram_chat_id
        if update:
            home_ref.update(update)
        print(f"Home '{home_id}' already exists; kept its settings" + (" and added members." if members else "."))
    if not home_ref.get().to_dict().get("memberEmails"):
        print("Note: memberEmails is empty, so nobody can read this home from the app. Rerun with --member you@gmail.com.")

    chunks = to_chunks(events, source="seed")
    for i in range(0, len(chunks), 400):             # a batch holds at most 500 writes
        batch = db.batch()
        for c in chunks[i:i + 400]:
            batch.set(home_ref.collection("timeline").document(chunk_id(c)), c)
        batch.commit()
    print(f"Wrote {len(events)} events in {len(chunks)} timeline documents.")

    if with_devices:
        now = datetime.now(timezone.utc)
        for room in sorted({e["room"] for e in events}):
            home_ref.collection("devices").document(device_id(room)).set(
                {"kind": "listener", "room": room, "lastHeartbeat": now, "online": True, "target": "hub"})
        print("Wrote listener heartbeats (they will look offline after a few minutes unless a real hub runs).")


def summary(events: list[dict], tz_name: str) -> str:
    tz = ZoneInfo(tz_name)
    by_day: dict[date, int] = {}
    for e in events:
        d = e["start"].astimezone(tz).date()
        by_day[d] = by_day.get(d, 0) + 1
    lines = [f"{d} {d.strftime('%a')}: {n} events" for d, n in sorted(by_day.items())]
    return "\n".join(lines) + f"\nTotal: {len(events)} events over {len(by_day)} days."


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Write fake history for a Nonna Watch home (C4).")
    ap.add_argument("--home", default="maria")
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--member", action="append", default=[], help="family email allowed to read the home (repeatable)")
    ap.add_argument("--telegram-chat-id", default="")
    ap.add_argument("--seed", type=int, default=42, help="random seed; same number = same history")
    ap.add_argument("--clear", action="store_true", help="delete earlier seed events first")
    ap.add_argument("--with-devices", action="store_true")
    ap.add_argument("--emulator", action="store_true", help="write to the local emulator, not the real project")
    ap.add_argument("--key", help="path to the service-account key (real project only)")
    ap.add_argument("--dry-run", action="store_true", help="print what would be written, write nothing")
    ap.add_argument("--today-until", metavar="HH:MM", help="also write today's normal events up to this time")
    ap.add_argument("--skip-room", action="append", default=[], help="with --today-until: leave this room silent today")
    args = ap.parse_args(argv)

    tz_name = "Europe/Rome"
    events = generate(args.days, tz_name, seed=args.seed)
    if args.today_until:
        events += generate_today(args.today_until, args.skip_room, tz_name)
    print(summary(events, tz_name))
    if args.dry_run:
        return

    from nonna_cloud.db import connect
    db = connect(emulator=args.emulator, key=args.key)
    if args.clear:
        print(f"Deleted {clear_seed_events(db, args.home)} old seed timeline documents.")
    write(db, args.home, events, args.member, args.telegram_chat_id, args.with_devices)


if __name__ == "__main__":
    main()
