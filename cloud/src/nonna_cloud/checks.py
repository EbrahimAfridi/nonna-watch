"""C5: run the routine / silence / offline checks against Firestore.

The logic lives in routine.py. This file only reads what it needs, calls it, and writes alerts.

Run it from cloud/ (all flags optional):

    uv run python -m nonna_cloud.checks                    # check once now, print findings, write nothing
    uv run python -m nonna_cloud.checks --now 10:30        # pretend it's 10:30 today (fake clock, for the demo)
    uv run python -m nonna_cloud.checks --report           # also write alerts to Firestore
    uv run python -m nonna_cloud.checks --report --telegram   # ...and post them to the family group
    uv run python -m nonna_cloud.checks --loop             # every 15 minutes, forever (Ctrl+C stops)
    add --emulator to use the local emulator instead of the real project.

Used from the hub (Path B, task E9), so the hub can run the voice check before alerting:

    from nonna_cloud.checks import Checker
    checker = Checker(db, "maria")            # db = the hub's firestore client
    for f in checker.run():                    # every 15 minutes
        if f.voice_check:
            result = hub.ask_are_you_okay(f.room)          # "fine" / "help" / "no_answer"
            if result == "fine":
                continue
            checker.report(f, voice_result=result)
        else:
            checker.report(f)
        telegram.send(f.message)

Cost per run (Spark free tier: 50,000 reads and 20,000 writes a day): the last 24 hours of timeline
documents (one per room per minute at most, usually far fewer) plus the devices; relearning reads 14 days
of timeline, but only once a day. In the demo home that is a few thousand reads a day.
"""

from __future__ import annotations

import argparse
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from nonna_cloud.routine import Finding, Routine, learn, run_checks, settings_for
from nonna_cloud.timeline import flatten, overlaps

HISTORY_DAYS = 14


class Checker:
    def __init__(self, db, home_id: str):
        self.db = db
        self.home_id = home_id
        self.home_ref = db.collection("homes").document(home_id)
        self._routines: dict[str, Routine] | None = None
        self._learned_for = None          # local date the cached routines were learned for

    # ---------------------------------------------------------------- reading

    def _events_since(self, since: datetime, until: datetime | None = None) -> list[dict]:
        """Flat events (timeline.py) that overlap [since, until). Reads the D20 chunk documents."""
        from google.cloud.firestore_v1.base_query import FieldFilter
        # One range filter only (no composite index needed); the `until` side is filtered here.
        q = self.home_ref.collection("timeline").where(filter=FieldFilter("end", ">=", since))
        chunks = [d.to_dict() for d in q.stream()]
        return [e for e in flatten(chunks) if overlaps(e, since, until)]

    def routines(self, now: datetime, tz: ZoneInfo, min_share: float) -> dict[str, Routine]:
        """Learned routines for today. Relearned at most once a day, then cached."""
        today = now.astimezone(tz).date()
        if self._learned_for == today and self._routines is not None:
            return self._routines

        # Maybe another run (or the Cloud Function) already learned today: reuse it.
        stored = {d.id: d.to_dict() for d in self.home_ref.collection("routines").stream()}
        act = stored.get("_activity")
        if act and act.get("learnedFor") == today.isoformat():
            self._routines = {k: Routine.from_doc(v) for k, v in stored.items()}
        else:
            self._routines = self.learn(now, tz, min_share, old_ids=set(stored))
        self._learned_for = today
        return self._routines

    def learn(self, now: datetime, tz: ZoneInfo, min_share: float, old_ids: set[str] = frozenset()) -> dict[str, Routine]:
        """Learn from the last 14 full days (not today) and store the result in homes/{id}/routines."""
        midnight = now.astimezone(tz).replace(hour=0, minute=0, second=0, microsecond=0)
        history = self._events_since(midnight - timedelta(days=HISTORY_DAYS), until=midnight)
        routines = learn(history, tz, min_share)

        batch, n = self.db.batch(), 0
        stamp = {"updatedAt": datetime.now(timezone.utc), "learnedFor": midnight.date().isoformat()}
        for rid, r in routines.items():
            batch.set(self.home_ref.collection("routines").document(rid), {**r.to_doc(), **stamp})
            n += 1
        for rid in old_ids - set(routines):          # habits that disappeared
            batch.delete(self.home_ref.collection("routines").document(rid))
            n += 1
        if n:
            batch.commit()
        return routines

    # ---------------------------------------------------------------- checking

    def run(self, now: datetime | None = None) -> list[Finding]:
        """Findings at `now` that have not been reported yet."""
        now = now or datetime.now(timezone.utc)
        home = self.home_ref.get().to_dict()
        if home is None:
            raise SystemExit(f"No home '{self.home_id}' in Firestore.")
        tz = ZoneInfo(home.get("timezone", "Europe/Rome"))
        s = settings_for(home)

        routines = self.routines(now, tz, s["routineMinShare"])
        recent = [e for e in self._events_since(now - timedelta(hours=24)) if e["start"] <= now]
        devices = {d.id: d.to_dict() for d in self.home_ref.collection("devices").stream()}

        findings = run_checks(home, routines, recent, devices, now)
        alerts = self.home_ref.collection("alerts")
        return [f for f in findings if not alerts.document(f.alert_id).get().exists]

    def report(self, f: Finding, voice_result: str | None = None) -> dict:
        """Write the alert document (schema: homes/{id}/alerts). Returns what was written."""
        doc = {
            "type": f.type,
            "severity": f.severity,
            "room": f.room,
            "time": f.time,
            "message": f.message,
            "detail": f.detail,
            "status": "sent",
            "answeredBy": None,
            "seenAt": None,
            "resolvedAt": None,
            "voiceCheck": {"asked": True, "result": voice_result} if voice_result else None,
            "followUp": None,
            "source": "routine",
        }
        # create() fails if it already exists, so two checkers can't report the same thing twice.
        try:
            self.home_ref.collection("alerts").document(f.alert_id).create(doc)
        except Exception as e:                     # google.api_core.exceptions.AlreadyExists
            if type(e).__name__ != "AlreadyExists":
                raise
        return doc


# -------------------------------------------------------------------- command line

def _parse_now(text: str | None, tz: ZoneInfo) -> datetime | None:
    """'10:30' -> today 10:30 local; '2026-11-27T10:30' -> that time local; None -> real clock."""
    if not text:
        return None
    if "T" in text:
        t = datetime.fromisoformat(text)
        return t if t.tzinfo else t.replace(tzinfo=tz)
    hh, mm = (int(x) for x in text.split(":"))
    return datetime.now(tz).replace(hour=hh, minute=mm, second=0, microsecond=0)


def _once(checker: Checker, now: datetime | None, report: bool, telegram: bool) -> None:
    findings = checker.run(now)
    when = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo("Europe/Rome")).strftime("%Y-%m-%d %H:%M")
    if not findings:
        print(f"[{when}] all normal")
        return
    chat_id = checker.home_ref.get().to_dict().get("telegramChatId", "") if telegram else ""
    for f in findings:
        ask = "  (the hub asks 'Are you okay?' first)" if f.voice_check else ""
        print(f"[{when}] {f.type}: {f.message}{ask}")
        if report:
            checker.report(f)
            if telegram:
                if chat_id:
                    from nonna_cloud.telegram_setup import send_message
                    send_message(chat_id, "⚠️ " + f.message)
                else:
                    print("   (no telegramChatId on the home, so nothing was posted)")
    if report:
        print(f"Wrote {len(findings)} alert(s).")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Routine, silence and offline checks (C5).")
    ap.add_argument("--home", default="maria")
    ap.add_argument("--now", help="fake clock: '10:30' (today) or '2026-11-27T10:30'")
    ap.add_argument("--report", action="store_true", help="write alerts to Firestore")
    ap.add_argument("--telegram", action="store_true", help="with --report: also post to the family group")
    ap.add_argument("--loop", action="store_true", help="repeat every --every minutes")
    ap.add_argument("--every", type=float, default=15)
    ap.add_argument("--emulator", action="store_true")
    ap.add_argument("--key")
    args = ap.parse_args(argv)

    from nonna_cloud.db import connect
    checker = Checker(connect(emulator=args.emulator, key=args.key), args.home)
    now = _parse_now(args.now, ZoneInfo("Europe/Rome"))
    while True:
        _once(checker, now, args.report, args.telegram)
        if not args.loop:
            return
        time.sleep(args.every * 60)
        now = None if not args.now else now + timedelta(minutes=args.every)


if __name__ == "__main__":
    main()
