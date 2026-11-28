"""Log a listener phone's battery, temperature and app CPU through adb (Experiment 5).

Experiment 5 compares two modes for an hour each, phone UNPLUGGED:
  streaming   the listener app streams audio to the hub
  local       the listener app runs YAMNet itself (phone-only mode, A10)

    uv run python -m nonna_exp.battery --mode streaming --minutes 60
    uv run python -m nonna_exp.battery --mode local --minutes 60

adb is Android's command-line tool (it comes with Android Studio: platform-tools/adb). The phone needs
"USB debugging" on. To measure a REAL battery drain the cable must be out, so connect adb over Wi-Fi:
    adb tcpip 5555          (with the cable in)
    adb connect <phone-ip>:5555
    then unplug the cable.
(`adb shell dumpsys battery unplug` only makes the phone REPORT unplugged; it still charges.)

One row per --every seconds: battery %, temperature in °C, voltage, charging or not, and the app's CPU
percent from `top`. Battery % per hour is computed later by charts.py from the first and last rows.
"""

from __future__ import annotations

import argparse
import csv
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

from nonna_exp import RESULTS

PACKAGE = "app.nonnawatch.listener"
FIELDS = ["time", "mode", "label", "level_pct", "temp_c", "voltage_v", "charging", "app_cpu_pct"]


def adb(*args: str, serial: str | None = None) -> str:
    exe = shutil.which("adb") or "adb"
    cmd = [exe, *(["-s", serial] if serial else []), *args]
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20).stdout


def parse_battery(text: str) -> dict:
    """`dumpsys battery` prints lines like '  level: 87', '  temperature: 312' (tenths of °C)."""
    values = {}
    for line in text.splitlines():
        key, sep, value = line.strip().partition(":")
        if sep:
            values[key.strip().lower()] = value.strip()
    plugged = any(values.get(k) == "true" for k in ("ac powered", "usb powered", "wireless powered"))
    return {
        "level_pct": int(values["level"]) if "level" in values else None,
        "temp_c": int(values["temperature"]) / 10 if "temperature" in values else None,
        "voltage_v": int(values["voltage"]) / 1000 if "voltage" in values else None,
        "charging": plugged,
    }


def parse_top(text: str, package: str) -> float | None:
    """The %CPU column of the app's line in `top -b -n 1`. Column positions vary by phone, so read the header."""
    header = None
    for line in text.splitlines():
        if "%CPU" in line and header is None:
            # Android's toybox top glues two titles together: "S[%CPU]". The data rows don't.
            header = line.replace("[%CPU]", " %CPU ").split()
            continue
        cols = line.split()
        if header and cols and package in cols[-1]:
            try:
                return float(cols[header.index("%CPU")].rstrip("%"))
            except (ValueError, IndexError):
                return None
    return None


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Log a phone's battery and app CPU over adb (C7, Experiment 5).")
    ap.add_argument("--mode", required=True, help="streaming / local, or any label")
    ap.add_argument("--label", default="")
    ap.add_argument("--package", default=PACKAGE)
    ap.add_argument("--serial", help="which phone, if adb sees more than one (adb devices)")
    ap.add_argument("--every", type=float, default=60)
    ap.add_argument("--minutes", type=float, default=60)
    ap.add_argument("--out", type=Path, default=RESULTS / "exp5_battery.csv")
    args = ap.parse_args(argv)

    if not shutil.which("adb"):
        raise SystemExit("adb not found. Add Android Studio's platform-tools folder to PATH (see the docstring).")
    first = parse_battery(adb("shell", "dumpsys", "battery", serial=args.serial))
    if first["level_pct"] is None:
        raise SystemExit("adb answered, but not with battery data. Is the phone connected (`adb devices`)?")
    if first["charging"]:
        print("Warning: the phone is charging, so the battery numbers won't show the real drain.")

    new = not args.out.exists()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    end = time.monotonic() + args.minutes * 60
    with args.out.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        print(f"Logging every {args.every:g} s for {args.minutes:g} min to {args.out}. Ctrl+C stops.")
        try:
            while True:
                row = parse_battery(adb("shell", "dumpsys", "battery", serial=args.serial))
                row["app_cpu_pct"] = parse_top(adb("shell", "top", "-b", "-n", "1", serial=args.serial), args.package)
                row.update(time=datetime.now().isoformat(timespec="seconds"), mode=args.mode, label=args.label)
                w.writerow(row)
                f.flush()
                print(f"{row['time']}  {row['level_pct']}%  {row['temp_c']} °C  app CPU {row['app_cpu_pct']}")
                if time.monotonic() >= end:
                    break
                time.sleep(args.every)
        except KeyboardInterrupt:
            pass
    print("Done.")


if __name__ == "__main__":
    main()
