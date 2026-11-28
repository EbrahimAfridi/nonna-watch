"""How much data leaves the house (Experiments 2 and 7).

Two setups:
  cloud   the phones stream ALL audio out of the house to Cloud Run. Per listener that is one frame per
          second of 32,012 bytes (docs/api-contract.md: 12-byte header + 1 s of 16 kHz 16-bit audio).
  edge    the audio stays in the house; only labels leave: the events and alerts the hub writes to
          Firestore (D30: one document per event), plus a heartbeat every 5 minutes.

    uv run python -m nonna_exp.datavolume --listeners 3                    # uses the formula for labels
    uv run python -m nonna_exp.datavolume --listeners 3 --from-firestore   # counts a real day in Firestore
    uv run python -m nonna_exp.datavolume --from-firestore --day 2026-12-01 --home maria

The label size is the JSON size of each document, a fair stand-in for what Firestore sends (its real
wire format adds some overhead, so the true number is a bit higher; it does not change the conclusion,
which is a factor of tens of thousands). Experiment 7 ("how private") is the raw-audio column:
streamed audio for cloud, zero for edge.
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from nonna_exp import RESULTS

FRAME_BYTES = 32_012               # per listener per second (api-contract.md)
SECONDS_PER_DAY = 86_400
HEARTBEATS_PER_DAY = 24 * 60 // 5  # D7: every 5 minutes
TYPICAL_EVENT_BYTES = 200          # one event document as JSON (measured on the seed data)
FIELDS = ["setup", "listeners", "events_per_day", "label_bytes_per_day", "audio_bytes_per_day",
          "bytes_per_day", "kb_per_minute", "source"]


def doc_bytes(doc: dict) -> int:
    return len(json.dumps(doc, default=str, ensure_ascii=False).encode("utf-8"))


def streamed(listeners: int) -> int:
    return FRAME_BYTES * SECONDS_PER_DAY * listeners


def from_firestore(home: str, day: date, emulator: bool) -> tuple[int, int]:
    """(number of event+alert documents, their total bytes) for one local day."""
    from google.cloud.firestore_v1.base_query import FieldFilter  # only needed here
    from nonna_cloud.db import connect

    tz = ZoneInfo("Europe/Rome")
    start = datetime(day.year, day.month, day.day, tzinfo=tz)
    end = start + timedelta(days=1)
    h = connect(emulator=emulator).collection("homes").document(home)
    docs = [d.to_dict() for d in h.collection("events").where(filter=FieldFilter("start", ">=", start))
            .where(filter=FieldFilter("start", "<", end)).stream()]
    docs += [d.to_dict() for d in h.collection("alerts").where(filter=FieldFilter("time", ">=", start))
             .where(filter=FieldFilter("time", "<", end)).stream()]
    return len(docs), sum(doc_bytes(d) for d in docs)


def rows(listeners: int, events_per_day: int, label_bytes: int, source: str) -> list[dict]:
    heartbeat_bytes = HEARTBEATS_PER_DAY * (listeners + 1) * 120     # small device documents
    edge = label_bytes + heartbeat_bytes
    cloud_audio = streamed(listeners)
    out = []
    for setup, audio, labels in (("edge", 0, edge), ("cloud", cloud_audio, edge)):
        total = audio + labels
        out.append({"setup": setup, "listeners": listeners, "events_per_day": events_per_day,
                    "label_bytes_per_day": labels, "audio_bytes_per_day": audio, "bytes_per_day": total,
                    "kb_per_minute": round(total / 1440 / 1000, 3), "source": source})
    return out


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1000:
            return f"{n:.1f} {unit}"
        n /= 1000
    return f"{n:.1f} TB"


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Data leaving the house: streaming vs labels (C7, Experiments 2 and 7).")
    ap.add_argument("--listeners", type=int, default=3)
    ap.add_argument("--events-per-day", type=int, default=30, help="used without --from-firestore")
    ap.add_argument("--from-firestore", action="store_true", help="measure a real day's documents instead")
    ap.add_argument("--home", default="maria")
    ap.add_argument("--day", type=date.fromisoformat, default=date.today() - timedelta(days=1))
    ap.add_argument("--emulator", action="store_true")
    ap.add_argument("--out", type=Path, default=RESULTS / "exp2_data_volume.csv")
    args = ap.parse_args(argv)

    if args.from_firestore:
        n, size = from_firestore(args.home, args.day, args.emulator)
        result = rows(args.listeners, n, size, f"firestore {args.home} {args.day}")
    else:
        result = rows(args.listeners, args.events_per_day, args.events_per_day * TYPICAL_EVENT_BYTES, "formula")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(result)
    for r in result:
        print(f"{r['setup']:<6} {human(r['bytes_per_day']):>10} per day   raw audio leaving: {human(r['audio_bytes_per_day'])}")
    print(f"Saved to {args.out}")


if __name__ == "__main__":
    main()
