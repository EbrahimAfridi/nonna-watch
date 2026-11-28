"""Turn the CSVs in results/ into the PNG charts in charts/ (never draw charts by hand, CONTEXT.md §9).

    uv run python -m nonna_exp.charts

Each chart is made only if its CSV exists, so this can run at any point of the project.
Every chart reports the average AND the worst case, as the requirements ask.

Colours: one fixed colour per setup, the same in every chart (edge blue, cloud orange, phone-only aqua),
checked for colour-blind readers. Values are always written on the chart too, never colour alone.
"""

from __future__ import annotations

import csv
import statistics
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")                     # draw to files, no window
import matplotlib.pyplot as plt  # noqa: E402

from nonna_exp import CHARTS, RESULTS  # noqa: E402

SETUP_COLOR = {"edge": "#257de0", "cloud": "#f47230", "phone": "#00b894"}
SETUP_NAME = {"edge": "Edge (laptop hub)", "cloud": "Cloud (Cloud Run, Milan)", "phone": "Phone only"}
SETUP_ORDER = ["edge", "cloud", "phone"]
HOP_COLORS = ["#84b9f3", "#257de0", "#0f4a96"]          # one hue, light -> dark: the three hops in order
TEXT, TEXT_2, GRID, SURFACE = "#191919", "#666666", "#e6e6e6", "#ffffff"
SINGLE = "#257de0"

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": GRID, "axes.labelcolor": TEXT_2, "xtick.color": TEXT_2, "ytick.color": TEXT_2,
    "text.color": TEXT, "axes.titlecolor": TEXT, "axes.titlesize": 13, "axes.titleweight": "bold",
    "axes.titlelocation": "left", "font.size": 10, "axes.grid": True, "grid.color": GRID,
    "grid.linewidth": 0.8, "axes.axisbelow": True, "axes.spines.top": False, "axes.spines.right": False,
    "legend.frameon": False, "figure.dpi": 150,
})


def read(name: str) -> list[dict]:
    path = RESULTS / name
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def num(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def save(fig, name: str) -> Path:
    CHARTS.mkdir(parents=True, exist_ok=True)
    path = CHARTS / name
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    print(f"  {path.name}")
    return path


def title(ax, text: str, sub: str | None = None, extra_pad: float = 0) -> None:
    """Bold title, with an optional grey line under it (room is left so the two never overlap)."""
    ax.set_title(text, pad=(20 if sub else 8) + extra_pad)
    if sub:
        ax.annotate(sub, xy=(0, 1), xycoords="axes fraction", xytext=(0, 6 + extra_pad),
                    textcoords="offset points", color=TEXT_2, fontsize=9, va="bottom")


# ------------------------------------------------------------------ Experiment 1 (and 6)

def alert_time(rows: list[dict], network: str = "normal") -> Path | None:
    """Mean bar and worst-case tick per setup: seconds from the sound to Telegram accepting the alert."""
    data = defaultdict(list)
    for r in rows:
        if r.get("status") == "sent" and (r.get("network") or "normal") == network and num(r.get("sent_s")) is not None:
            data[r["setup"]].append(num(r["sent_s"]))
    setups = [s for s in SETUP_ORDER if data[s]]
    if not setups:
        return None
    fig, ax = plt.subplots(figsize=(7, 0.9 + 0.7 * len(setups)))
    for i, s in enumerate(setups):
        mean, worst = statistics.mean(data[s]), max(data[s])
        ax.barh(i, mean, height=0.45, color=SETUP_COLOR[s])
        ax.plot([worst, worst], [i - 0.3, i + 0.3], color=TEXT, linewidth=2)
        ax.text(worst, i, f"  avg {mean:.1f} s · worst {worst:.1f} s · n={len(data[s])}",
                va="center", ha="left", color=TEXT, fontsize=9)
    ax.set_yticks(range(len(setups)), [SETUP_NAME[s] for s in setups])
    ax.invert_yaxis()
    ax.set_xlabel("seconds from the sound to the alert being sent")
    ax.set_xlim(0, max(max(data[s]) for s in setups) * 1.8)
    ax.grid(axis="y", visible=False)
    title(ax, "How fast does the family hear about it?" if network == "normal" else f"Alert time on a {network} network",
          "bar = average, black tick = worst case")
    return save(fig, "exp1_alert_time.png" if network == "normal" else f"exp6_alert_time_{network}.png")


def hops(rows: list[dict]) -> Path | None:
    """Where the time goes, per setup: audio to the hub, the AI, sending to Telegram (averages)."""
    parts = defaultdict(lambda: [[], [], []])
    for r in rows:
        rx, det, sent = num(r.get("received_s")), num(r.get("detected_s")), num(r.get("sent_s"))
        if r.get("status") == "sent" and (r.get("network") or "normal") == "normal" and None not in (rx, det, sent):
            p = parts[r["setup"]]
            p[0].append(rx)
            p[1].append(det - rx)
            p[2].append(sent - det)
    setups = [s for s in SETUP_ORDER if parts[s][0]]
    if not setups:
        return None
    names = ["audio reaches the AI", "AI decides", "message sent"]
    fig, ax = plt.subplots(figsize=(7, 1.2 + 0.7 * len(setups)))
    for i, s in enumerate(setups):
        left = 0.0
        for j, values in enumerate(parts[s]):
            w = statistics.mean(values)
            ax.barh(i, w, left=left, height=0.45, color=HOP_COLORS[j], edgecolor=SURFACE, linewidth=2,
                    label=names[j] if i == 0 else None)
            if w > 0.15:
                ax.text(left + w / 2, i, f"{w:.1f}", ha="center", va="center", fontsize=8,
                        color=TEXT if j == 0 else SURFACE)
            left += w
    ax.set_yticks(range(len(setups)), [SETUP_NAME[s] for s in setups])
    ax.invert_yaxis()
    ax.set_xlabel("seconds (average)")
    ax.grid(axis="y", visible=False)
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.0), ncol=3, fontsize=9, borderaxespad=0.3)
    title(ax, "Where the time goes", extra_pad=22)
    return save(fig, "exp1_hops.png")


def network_effect(rows: list[dict]) -> Path | None:
    """Experiment 6: average alert time, normal vs slowed network, per setup."""
    data = defaultdict(list)
    for r in rows:
        if r.get("status") == "sent" and num(r.get("sent_s")) is not None:
            data[(r["setup"], r.get("network") or "normal")].append(num(r["sent_s"]))
    networks = sorted({n for (_, n) in data}, key=lambda n: (n != "normal", n))
    setups = [s for s in SETUP_ORDER if any((s, n) in data for n in networks)]
    if len(networks) < 2 or not setups:
        return None
    fig, ax = plt.subplots(figsize=(7, 1 + 0.9 * len(setups)))
    h = 0.8 / len(networks)
    for i, s in enumerate(setups):
        for j, n in enumerate(networks):
            vals = data.get((s, n))
            if not vals:
                continue
            y = i - 0.4 + h * (j + 0.5)
            ax.barh(y, statistics.mean(vals), height=h * 0.85, color=SETUP_COLOR[s],
                    hatch=None if n == "normal" else "///", edgecolor=SURFACE, linewidth=0)
            ax.text(statistics.mean(vals), y, f"  {n}: avg {statistics.mean(vals):.1f} s, worst {max(vals):.1f} s",
                    va="center", fontsize=8)
    ax.set_yticks(range(len(setups)), [SETUP_NAME[s] for s in setups])
    ax.invert_yaxis()
    ax.set_xlim(0, max(max(v) for v in data.values()) * 1.9)
    ax.set_xlabel("seconds from the sound to the alert being sent")
    ax.grid(axis="y", visible=False)
    title(ax, "What a bad network does", "plain bar = normal network, striped = slowed down")
    return save(fig, "exp6_network.png")


# ------------------------------------------------------------------ Experiments 2 and 7

def data_volume(rows: list[dict]) -> Path | None:
    rows = [r for r in rows if r.get("setup") in SETUP_COLOR and num(r.get("bytes_per_day"))]
    if not rows:
        return None
    rows.sort(key=lambda r: SETUP_ORDER.index(r["setup"]))
    fig, ax = plt.subplots(figsize=(7, 2.2))
    for i, r in enumerate(rows):
        total, audio = num(r["bytes_per_day"]), num(r["audio_bytes_per_day"])
        ax.barh(i, total, height=0.45, color=SETUP_COLOR[r["setup"]])
        ax.text(total * 1.15, i, f"{human(total)} per day  (raw audio: {human(audio)})", va="center", fontsize=9)
    ax.set_xscale("log")
    ax.set_xlim(min(num(r["bytes_per_day"]) for r in rows) / 3, max(num(r["bytes_per_day"]) for r in rows) * 400)
    ax.set_yticks(range(len(rows)), [SETUP_NAME[r["setup"]] for r in rows])
    ax.invert_yaxis()
    ax.set_xlabel("bytes leaving the house per day (log scale: each step is 10×)")
    ax.grid(axis="y", visible=False)
    title(ax, "How much data leaves the house?",
          f"{rows[0]['listeners']} listeners; edge sends labels only, cloud streams all audio")
    return save(fig, "exp2_data_volume.png")


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1000:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1000
    return f"{n:.1f} TB"


# ------------------------------------------------------------------ Experiment 3

def detection(rows: list[dict]) -> Path | None:
    groups = defaultdict(list)
    false_alarms, hours = 0, 0.0
    for r in rows:
        if r.get("caught") in ("0", "1"):
            key = f"help ({r['lang']})" if r["kind"] == "help" else r["expected"]
            groups[key].append(int(r["caught"]))
        if r.get("kind") in ("tv", "radio"):
            false_alarms += int(r.get("false_alarms") or 0)
            hours += (num(r.get("duration_s")) or 0) / 3600
    if not groups:
        return None
    keys = sorted(groups, key=lambda k: (not k.startswith("help"), k))
    fig, ax = plt.subplots(figsize=(7, 0.9 + 0.45 * len(keys)))
    for i, k in enumerate(keys):
        share = sum(groups[k]) / len(groups[k])
        ax.barh(i, share * 100, height=0.5, color=SINGLE)
        ax.text(share * 100 + 1.5, i, f"{sum(groups[k])}/{len(groups[k])}", va="center", fontsize=9)
    ax.set_yticks(range(len(keys)), keys)
    ax.invert_yaxis()
    ax.set_xlim(0, 112)
    ax.set_xlabel("% of real events caught")
    ax.grid(axis="y", visible=False)
    fa = f"{false_alarms / hours:.1f} false alarms per hour of TV/radio ({hours:.1f} h tested)" if hours else "no TV/radio tested yet"
    title(ax, "How good is the detection?", fa)
    return save(fig, "exp3_detection.png")


# ------------------------------------------------------------------ Experiment 4

def whisper_sizes(rows: list[dict]) -> Path | None:
    if not rows:
        return None
    sizes = [s for s in ("tiny", "base", "small") if any(r["size"] == s for r in rows)]
    langs = sorted({r["lang"] for r in rows})
    size_colors = dict(zip(("tiny", "base", "small"), HOP_COLORS))      # ordered sizes: one hue light -> dark
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(10, 0.9 + 0.55 * len(langs) * len(sizes) / 2 + 1),
                                 gridspec_kw={"width_ratios": [3, 2]})
    h = 0.8 / len(sizes)
    for i, lang in enumerate(langs):
        for j, s in enumerate(sizes):
            vals = [int(r["caught"]) for r in rows if r["lang"] == lang and r["size"] == s]
            if not vals:
                continue
            y = i - 0.4 + h * (j + 0.5)
            a1.barh(y, 100 * sum(vals) / len(vals), height=h * 0.85, color=size_colors[s],
                    label=s if i == 0 else None)
            a1.text(100 * sum(vals) / len(vals) + 1.5, y, f"{sum(vals)}/{len(vals)}", va="center", fontsize=8)
    a1.set_yticks(range(len(langs)), langs)
    a1.invert_yaxis()
    a1.set_xlim(0, 115)
    a1.set_xlabel("% of help words caught")
    a1.grid(axis="y", visible=False)
    a1.legend(loc="lower left", bbox_to_anchor=(0, 1.0), ncol=3, fontsize=8, borderaxespad=0.3)
    title(a1, "Help words caught, per language", extra_pad=20)
    for j, s in enumerate(sizes):
        secs = [float(r["seconds"]) for r in rows if r["size"] == s]
        a2.barh(j, statistics.mean(secs), height=0.5, color=size_colors[s])
        a2.text(statistics.mean(secs), j, f"  avg {statistics.mean(secs):.2f} s, worst {max(secs):.2f} s",
                va="center", fontsize=8)
    a2.set_yticks(range(len(sizes)), sizes)
    a2.invert_yaxis()
    a2.set_xlim(0, max(float(r["seconds"]) for r in rows) * 2.2)
    a2.set_xlabel("seconds per clip on the laptop CPU")
    a2.grid(axis="y", visible=False)
    title(a2, "Speed", extra_pad=20)
    fig.tight_layout()
    return save(fig, "exp4_whisper_sizes.png")


# ------------------------------------------------------------------ Experiment 5 and laptop CPU

def battery(rows: list[dict]) -> Path | None:
    """One line per run (battery.py gives each run an id), never one line for several runs of a mode.
    Rows taken while the phone was charging are skipped: they would hide the drain."""
    by_run = defaultdict(list)
    for r in rows:
        if num(r.get("level_pct")) is None or str(r.get("charging", "")).lower() == "true":
            continue
        by_run[r.get("run") or r["mode"]].append(
            (datetime.fromisoformat(r["time"]), num(r["level_pct"]), num(r.get("app_cpu_pct"))))
    if not by_run:
        return None
    modes = [run.split(" ")[0] for run in by_run]
    # Name a line by its mode alone when that mode has only one run, else by mode and start time.
    names = {run: (run if modes.count(run.split(" ")[0]) > 1 else run.split(" ")[0]) for run in by_run}
    colors = ["#257de0", "#f47230", "#00b894", "#f2a600"]       # fixed order, by first appearance
    fig, ax = plt.subplots(figsize=(7, 3.2))
    for i, (run, pts) in enumerate(by_run.items()):
        pts.sort()
        mode = names[run]
        t0 = pts[0][0]
        xs = [(t - t0).total_seconds() / 60 for t, _, _ in pts]
        ys = [lvl for _, lvl, _ in pts]
        ax.plot(xs, ys, color=colors[i % len(colors)], linewidth=2, label=mode)
        hours = (xs[-1] - xs[0]) / 60
        rate = (ys[0] - ys[-1]) / hours if hours > 0 else 0
        cpus = [c for _, _, c in pts if c is not None]
        cpu = f", app CPU avg {statistics.mean(cpus):.0f}%" if cpus else ""
        ax.annotate(f"{mode}: {rate:.1f} %/h{cpu}", (xs[-1], ys[-1]), xytext=(6, 0),
                    textcoords="offset points", va="center", fontsize=9)
    ax.set_xlabel("minutes, phone unplugged")
    ax.set_ylabel("battery %")
    ax.legend(loc="lower left", fontsize=9)
    title(ax, "What does it cost the phone?")
    return save(fig, "exp5_battery.png")


def laptop_cpu(rows: list[dict]) -> Path | None:
    by_label = defaultdict(list)
    for r in rows:
        if num(r.get("hub_cpu_pct")) is not None:
            by_label[r.get("label") or "hub"].append((num(r["hub_cpu_pct"]), num(r["hub_mem_mb"])))
    if not by_label:
        return None
    labels = list(by_label)
    fig, ax = plt.subplots(figsize=(7, 0.9 + 0.6 * len(labels)))
    for i, lab in enumerate(labels):
        cpu = [c for c, _ in by_label[lab]]
        mem = max(m for _, m in by_label[lab])
        ax.barh(i, statistics.mean(cpu), height=0.45, color=SINGLE)
        ax.plot([max(cpu)] * 2, [i - 0.3, i + 0.3], color=TEXT, linewidth=2)
        ax.text(max(cpu), i, f"  avg {statistics.mean(cpu):.0f}%, worst {max(cpu):.0f}%, memory up to {mem:.0f} MB",
                va="center", fontsize=9)
    ax.set_yticks(range(len(labels)), labels)
    ax.invert_yaxis()
    ax.set_xlim(0, max(max(c for c, _ in v) for v in by_label.values()) * 2.4 + 1)
    ax.set_xlabel("hub CPU, % of one core")
    ax.grid(axis="y", visible=False)
    title(ax, "What does it cost the laptop?", "bar = average, black tick = worst case")
    return save(fig, "laptop_cpu.png")


def main() -> None:
    print(f"Charts from {RESULTS} into {CHARTS}:")
    t = read("exp1_alert_time.csv")
    made = [alert_time(t), hops(t), network_effect(t), data_volume(read("exp2_data_volume.csv")),
            detection(read("exp3_detection.csv")), whisper_sizes(read("exp4_whisper_sizes.csv")),
            battery(read("exp5_battery.csv")), laptop_cpu(read("laptop_cpu.csv"))]
    if not any(made):
        print("  (no results yet)")


if __name__ == "__main__":
    main()
