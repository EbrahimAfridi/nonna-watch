"""Log the hub's CPU and memory on the laptop while it runs (requirements: "laptop CPU").

    uv run python -m nonna_exp.cpu --minutes 10 --label "3 listeners, normal day"

Every --every seconds it writes one row: the hub's CPU (percent of ONE core, so 150 means one and a
half cores busy), its memory in MB, and the whole laptop's CPU. The hub is found by looking for
"nonna-hub" in each process's command line, children included (uv starts Python as a child).
"""

from __future__ import annotations

import argparse
import csv
import time
from datetime import datetime
from pathlib import Path

import psutil

from nonna_exp import RESULTS

FIELDS = ["time", "label", "hub_cpu_pct", "hub_mem_mb", "system_cpu_pct", "processes"]


def find(match: str) -> list[psutil.Process]:
    found = []
    for p in psutil.process_iter(["cmdline"]):
        try:
            if any(match in part for part in (p.info["cmdline"] or [])):
                found.append(p)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return found


def sample(procs: list[psutil.Process]) -> tuple[float, float]:
    cpu = mem = 0.0
    for p in procs:
        try:
            cpu += p.cpu_percent(None)
            mem += p.memory_info().rss / 1e6
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return cpu, mem


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Log the hub's CPU and memory (C7).")
    ap.add_argument("--match", default="nonna-hub", help="text to look for in the hub's command line")
    ap.add_argument("--every", type=float, default=1.0, help="seconds between samples")
    ap.add_argument("--minutes", type=float, default=10)
    ap.add_argument("--label", default="")
    ap.add_argument("--out", type=Path, default=RESULTS / "laptop_cpu.csv")
    args = ap.parse_args(argv)

    procs = find(args.match)
    if not procs:
        raise SystemExit(f"No running process with '{args.match}' in its command line. Is the hub running?")
    sample(procs)                                    # the first cpu_percent call only starts the clock
    psutil.cpu_percent(None)

    new = not args.out.exists()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    end = time.monotonic() + args.minutes * 60
    with args.out.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        print(f"Logging {len(procs)} hub process(es) for {args.minutes:g} min to {args.out}. Ctrl+C stops.")
        try:
            while time.monotonic() < end:
                time.sleep(args.every)
                cpu, mem = sample(procs)
                w.writerow({"time": datetime.now().isoformat(timespec="seconds"), "label": args.label,
                            "hub_cpu_pct": round(cpu, 1), "hub_mem_mb": round(mem, 1),
                            "system_cpu_pct": psutil.cpu_percent(None), "processes": len(procs)})
                f.flush()
        except KeyboardInterrupt:
            pass
    print("Done.")


if __name__ == "__main__":
    main()
