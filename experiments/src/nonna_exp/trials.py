"""Run one experiment N times (30 by default) and save one CSV row per trial (Experiments 1 and 6).

Start the hub first with `uv run python -m nonna_exp.record_hub` (it saves the output to hub.log).
Then, in a second terminal, from experiments/:

  Automatic, with a recording played through the hub's fake phone (no real phone needed):
    uv run python -m nonna_exp.trials --setup edge --clip data/help_it_anna_01.wav --room kitchen
    uv run python -m nonna_exp.trials --setup cloud --hub-url wss://<cloud-run-url>/ws/listener --clip ...

  By hand, with a real phone (you make the sound when told):
    uv run python -m nonna_exp.trials --setup edge --label "real phone, shout aiuto"

  A slow network for Experiment 6: turn on clumsy (Windows) first, and add --network slow.

Each trial only counts an alert from its own room, of the expected kind (--kind, or any kind except the
hub's offline / back_online / water_running notices), for a sound made after the trial started. So a late
alert from the previous trial, or a phone going offline, is never timed as this trial.

Each trial waits for the hub to report the alert as SENT (or NOT SENT), then waits until --gap seconds
have passed, because the hub allows one alert of each kind per room per minute (D26). 30 trials at
the default gap take about 35 minutes.

Rows are appended to --out (default results/exp1_alert_time.csv), so an interrupted run keeps
the trials it finished, and later runs (cloud, slow network...) add to the same file.
"""

from __future__ import annotations

import argparse
import csv
import os
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

from nonna_exp import EXPERIMENTS, HUB, RESULTS
from nonna_exp.hublog import AlertTiming, HubLogReader

NOT_TIMED = {"offline", "back_online", "water_running"}   # hub notices, not reactions to the trial's sound
CLOCK_SLACK_S = 2.0   # the sound's time comes from the phone's clock: allow it to be this far behind ours

FIELDS = ["trial", "setup", "network", "label", "clip", "room", "started", "kind", "detail",
          "received_s", "detected_s", "sent_s", "status", "error"]


def append_row(path: Path, row: dict) -> None:
    new = not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in FIELDS})


def start_fake_phone(clip: Path, room: str, hub_url: str) -> subprocess.Popen:
    uv = shutil.which("uv") or os.environ.get("UV", "uv")
    cmd = [uv, "run", "nonna-hub", "fake-phone", "--room", room, "--hub", hub_url, str(clip.resolve())]
    return subprocess.Popen(cmd, cwd=HUB, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)


def seconds_of_day(clock: str) -> float:
    """'14:03:12.5' -> seconds since midnight."""
    h, m, s = clock.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def belongs_to_trial(alert: AlertTiming, room: str, kinds: set[str] | None, started: str) -> bool:
    """Is this alert the reaction to the sound of the trial that started at `started` (HH:MM:SS.t)?"""
    if alert.room != room:
        return False
    if kinds is not None and alert.kind not in kinds:
        return False
    if kinds is None and alert.kind in NOT_TIMED:
        return False
    late = seconds_of_day(alert.at) - seconds_of_day(started)
    if late < -12 * 3600:          # the trial started before midnight and the sound came after it
        late += 24 * 3600
    return late >= -CLOCK_SLACK_S


def wait_for_alert(log: Path, offset: int, reader: HubLogReader, timeout_s: float, accept=None):
    """Read new lines of the hub log from `offset` until an alert completes. Returns (alert, new offset).

    `accept(alert)` decides which completed alerts count (default: all); the others are skipped.
    """
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        # Bytes, not text: the position must be exact, and Windows writes two characters per line end.
        with log.open("rb") as f:
            f.seek(offset)
            chunk = f.read()
        # Only consume whole lines; a half-written last line is read again next time.
        whole = chunk[: chunk.rfind(b"\n") + 1]
        offset += len(whole)
        done = [a for a in reader.feed(whole.decode("utf-8", errors="replace").splitlines())
                if accept is None or accept(a)]
        if done:
            return done[0], offset
        time.sleep(0.2)
    return None, offset


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Run an alert-timing experiment N times (C7).")
    ap.add_argument("--setup", required=True, choices=["edge", "cloud", "phone"], help="where the AI runs")
    ap.add_argument("--network", default="normal", help="normal / slow (Experiment 6), free text")
    ap.add_argument("--label", default="", help="free note saved with each row, e.g. 'real phone, aiuto'")
    ap.add_argument("--hub-log", type=Path, default=EXPERIMENTS / "hub.log", help="the hub's saved output")
    ap.add_argument("--clip", type=Path, help="play this recording through the fake phone (else: by hand)")
    ap.add_argument("--room", default="kitchen", help="the room of the phone (fake or real) used in the trials")
    ap.add_argument("--kind", action="append",
                    help="alert kind that counts, e.g. help_word (repeat for several; default: any reaction)")
    ap.add_argument("--hub-url", default="ws://localhost:8000/ws/listener")
    ap.add_argument("--trials", type=int, default=30)
    ap.add_argument("--gap", type=float, default=65, help="seconds from one trial's start to the next")
    ap.add_argument("--timeout", type=float, default=90, help="give up on a trial after this many seconds")
    ap.add_argument("--out", type=Path, default=RESULTS / "exp1_alert_time.csv")
    args = ap.parse_args(argv)

    if not args.hub_log.exists():
        raise SystemExit(f"No hub log at {args.hub_log}. Start the hub with its output saved there (see hublog.py).")
    reader = HubLogReader()
    offset = args.hub_log.stat().st_size            # ignore everything the hub printed before we started

    for n in range(1, args.trials + 1):
        t0 = time.monotonic()
        now = datetime.now()
        started = now.strftime("%H:%M:%S")
        started_clock = now.strftime("%H:%M:%S.") + str(now.microsecond // 100_000)
        phone = None
        if args.clip:
            phone = start_fake_phone(args.clip, args.room, args.hub_url)
            print(f"trial {n}/{args.trials}: playing {args.clip.name} ...", end=" ", flush=True)
        else:
            input(f"trial {n}/{args.trials}: make the sound now, then press Enter ")
        kinds = set(args.kind) if args.kind else None
        alert, offset = wait_for_alert(args.hub_log, offset, reader, args.timeout,
                                       accept=lambda a: belongs_to_trial(a, args.room, kinds, started_clock))
        if phone:
            try:
                phone.wait(timeout=30)
            except subprocess.TimeoutExpired:
                phone.kill()

        row = {"trial": n, "setup": args.setup, "network": args.network, "label": args.label,
               "clip": args.clip.name if args.clip else "", "room": args.room, "started": started}
        if alert is None:
            row.update(status="missed", error=f"no alert within {args.timeout:.0f} s")
            print("MISSED")
        else:
            row.update(alert.row())
            print(f"{alert.kind}: received +{alert.received_s} s, detected +{alert.detected_s} s, sent +{alert.sent_s} s")
        append_row(args.out, row)

        if n < args.trials:
            time.sleep(max(0.0, args.gap - (time.monotonic() - t0)))
    print(f"Saved to {args.out}")


if __name__ == "__main__":
    main()
