"""Experiment 3: how good is the detection? Runs the hub over the test set and scores it.

    uv run python -m nonna_exp.detection data/*.wav --languages it,en,hi,ur,bs

For every file, the hub's own `nonna-hub listen` command (the same YAMNet, VAD, Whisper and rules as
`serve`) prints what it heard. This script reads that output and compares it with what the file's
name says should happen (testset.py):

  help_*            caught if the hub printed HELP
  thud_/scream_/... caught if the hub heard that category (thud, scream, glass, ...)
  kitchen_/tv_/...  every ALERT is a false alarm (a help word prints HELP and then ALERT: that is ONE
                    alarm, so HELP lines are not counted again); tv_ and radio_ give false alarms per hour

Results: results/exp3_detection.csv (one row per file). charts.py summarises them.
Audio never leaves the laptop; nothing here sends anything.
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import shutil
import subprocess
import wave
from pathlib import Path

from nonna_exp import HUB, RESULTS
from nonna_exp.testset import Clip, parse

EVENT = re.compile(r"^\s*[\d.]+ to\s+[\d.]+ s\s+(?P<category>\w+)\s+[\d.]+\s")
HELP = re.compile(r"^\s*[\d.]+ to\s+[\d.]+ s\s+HELP\s+(?P<words>.+)$")
ALERT = re.compile(r"^\s*[\d.]+ s\s+ALERT\s+(?P<kind>\w+)")
FIELDS = ["file", "kind", "lang", "expected", "caught", "false_alarms", "categories", "help_words",
          "alerts", "duration_s"]


def split_by_file(output: str, names: list[str]) -> dict[str, list[str]]:
    """`listen` prints a blank line and the file name before each file's lines."""
    sections: dict[str, list[str]] = {}
    current = None
    for line in output.splitlines():
        if line.strip() in names:
            current = line.strip()
            sections[current] = []
        elif current is not None:
            sections[current].append(line)
    return sections


def read_section(lines: list[str]) -> dict:
    categories, helps, alerts = set(), [], []
    for line in lines:
        if m := HELP.match(line):
            helps.append(m["words"].strip())
        elif m := ALERT.match(line):
            alerts.append(m["kind"])
        elif m := EVENT.match(line):
            if m["category"] not in {"said", "HELP"}:
                categories.add(m["category"])
    return {"categories": sorted(categories), "help_words": helps, "alerts": alerts}


def score(clip: Clip, heard: dict, duration_s: float | None) -> dict:
    if clip.expect_help:
        expected, caught = "help word", bool(heard["help_words"])
    elif clip.expect_category:
        expected, caught = clip.expect_category, clip.expect_category in heard["categories"]
    else:
        expected, caught = "nothing", None
    # ALERT is what would reach the family. A help word also prints HELP first; counting both doubled it.
    false_alarms = len(heard["alerts"]) if clip.negative else 0
    return {"file": clip.path.name, "kind": clip.kind, "lang": clip.lang or "", "expected": expected,
            "caught": "" if caught is None else int(caught), "false_alarms": false_alarms,
            "categories": " ".join(heard["categories"]), "help_words": "; ".join(heard["help_words"]),
            "alerts": " ".join(heard["alerts"]), "duration_s": duration_s if duration_s is not None else ""}


def wav_seconds(path: Path) -> float | None:
    try:
        with wave.open(str(path)) as w:
            return round(w.getnframes() / w.getframerate(), 1)
    except (wave.Error, OSError, EOFError):
        return None


def run_hub(files: list[Path], languages: str) -> str:
    uv = shutil.which("uv") or os.environ.get("UV", "uv")
    cmd = [uv, "run", "nonna-hub", "listen", "--languages", languages, *[str(f.resolve()) for f in files]]
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    done = subprocess.run(cmd, cwd=HUB, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    if done.returncode != 0:
        raise SystemExit(f"The hub failed:\n{done.stderr[-2000:]}")
    return done.stdout


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Experiment 3: score the hub on the test set (C7).")
    ap.add_argument("files", nargs="+", type=Path)
    ap.add_argument("--languages", default="it,en,hi,ur,bs")
    ap.add_argument("--out", type=Path, default=RESULTS / "exp3_detection.csv")
    args = ap.parse_args(argv)

    clips = [parse(f) for f in args.files]
    print(f"Running the hub over {len(clips)} files (Whisper is slow on the first run) ...")
    sections = split_by_file(run_hub(args.files, args.languages), [f.name for f in args.files])
    results = [score(c, read_section(sections.get(c.path.name, [])), wav_seconds(c.path)) for c in clips]

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(results)
    caught = [r for r in results if r["caught"] != ""]
    print(f"Caught {sum(r['caught'] for r in caught)}/{len(caught)} real events; "
          f"{sum(r['false_alarms'] for r in results)} false alarms. Saved to {args.out}")


if __name__ == "__main__":
    main()
