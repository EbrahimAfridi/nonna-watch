"""Nonna Watch experiments (C7): tools that measure the system and draw the charts.

    hublog       read the hub's printed output and pull out each alert's timing
    trials       run an experiment N times (30 by default) and save one CSV row per trial
    cpu          log the laptop's CPU and memory while the hub runs
    battery      log a phone's battery, temperature and app CPU through adb
    datavolume   how much data leaves the house: streamed audio vs labels only
    testset      the naming rules for test recordings, and what each one should trigger
    detection    Experiment 3: run the hub over the test set and score what it caught
    whisper_sizes  Experiment 4: Whisper tiny vs base vs small, speed vs help words caught
    charts       turn the CSVs in results/ into the PNG charts in charts/

Raw results (CSV) go in experiments/results/ and are committed. Recordings go in experiments/data/,
which git ignores (too big): share them by link.
"""

import sys as _sys
from pathlib import Path

for _stream in (_sys.stdout, _sys.stderr):           # Windows consoles crash on "ć" otherwise
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

EXPERIMENTS = Path(__file__).resolve().parents[2]
REPO = EXPERIMENTS.parent
HUB = REPO / "hub"
RESULTS = EXPERIMENTS / "results"
CHARTS = EXPERIMENTS / "charts"
DATA = EXPERIMENTS / "data"
