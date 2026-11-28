"""Tests for the experiment tools (C7), with hub output in the exact format the hub prints."""

import csv
import random
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from nonna_exp import battery, charts, datavolume, detection, hublog, trials
from nonna_exp.testset import parse

HUB_OUTPUT = """\
Phones connect to ws://192.168.1.5:8000/ws/listener with HUB_TOKEN from hub/.env
kitchen      connected: Nothing CMF, app 0.1
kitchen      14:03:10.2 to 14:03:11.9   water        0.59  Water tap, faucet
bathroom     14:03:12.5   ALERT        help_word aiuto   received +0.3 s, detected +1.8 s
kitchen      14:05:00.0   ALERT        offline
bathroom     14:03:12.5   SENT         +2.1 s after the sound
bathroom     14:07:40.1   ALERT        thud after the check: no_answer   received +0.4 s, detected +41.2 s
kitchen      14:05:00.0   NOT SENT     network unreachable
bathroom     14:07:40.1   SENT         +41.9 s after the sound
"""


# ------------------------------------------------------------------ hublog

def test_reads_alert_timings_and_pairs_them_with_sent():
    alerts = hublog.parse(HUB_OUTPUT.splitlines())
    assert [(a.room, a.kind, a.status) for a in alerts] == [
        ("bathroom", "help_word", "sent"), ("kitchen", "offline", "not_sent"), ("bathroom", "thud", "sent")]
    help_word = alerts[0]
    assert (help_word.detail, help_word.received_s, help_word.detected_s, help_word.sent_s) == ("aiuto", 0.3, 1.8, 2.1)
    assert alerts[2].detail == "after the check: no_answer" and alerts[2].sent_s == 41.9
    assert alerts[1].received_s is None and alerts[1].error == "network unreachable"


def test_reader_reports_alerts_as_they_complete():
    r = hublog.HubLogReader()
    lines = HUB_OUTPUT.splitlines()
    assert r.feed(lines[:4]) == []                         # ALERT seen, SENT not yet
    done = r.feed(lines[4:6])
    assert [a.kind for a in done] == ["help_word"]


# ------------------------------------------------------------------ trials: reading a growing log

def test_waiting_reads_only_whole_new_lines(tmp_path):
    log = tmp_path / "hub.log"
    log.write_bytes(b"old line\r\n")
    offset = log.stat().st_size
    with log.open("ab") as f:                              # Windows line ends, last line half-written
        f.write("bathroom     14:03:12.5   ALERT        help_word aiuto   received +0.3 s, detected +1.8 s\r\n".encode())
        f.write(b"bathroom     14:03:12.5   SENT         +2.1 s af")
    reader = hublog.HubLogReader()
    alert, offset2 = trials.wait_for_alert(log, offset, reader, timeout_s=0.5)
    assert alert is None                                   # SENT line not finished yet
    with log.open("ab") as f:
        f.write(b"ter the sound\r\n")
    alert, _ = trials.wait_for_alert(log, offset2, reader, timeout_s=2)
    assert alert is not None and alert.sent_s == 2.1


def test_rows_are_appended_with_one_header(tmp_path):
    out = tmp_path / "r.csv"
    trials.append_row(out, {"trial": 1, "setup": "edge"})
    trials.append_row(out, {"trial": 2, "setup": "edge"})
    rows = list(csv.DictReader(out.open(encoding="utf-8")))
    assert [r["trial"] for r in rows] == ["1", "2"]


# ------------------------------------------------------------------ test set names

@pytest.mark.parametrize("name, kind, lang, help_, category, negative", [
    ("help_it_anna_03.wav", "help", "it", True, None, False),
    ("thud_bag_07.wav", "thud", None, False, "thud", False),
    ("glass_esc50_12.wav", "glass", None, False, "glass", False),
    ("tv_rai1_01.wav", "tv", None, False, None, True),
    ("esc50_glass_breaking_17.wav", "esc50", None, False, "glass", False),
    ("esc50_dog_3.wav", "esc50", None, False, None, True),
])
def test_file_names_say_what_should_happen(name, kind, lang, help_, category, negative):
    c = parse(Path(name))
    assert (c.kind, c.lang, c.expect_help, c.expect_category, c.negative) == (kind, lang, help_, category, negative)


def test_help_clip_without_language_is_refused():
    with pytest.raises(ValueError):
        parse(Path("help_anna_01.wav"))


# ------------------------------------------------------------------ Experiment 3 scoring

LISTEN_OUTPUT = """
help_it_anna_01.wav
    0.0 to   1.4 s   speech       0.71  Speech
    0.2 to   1.3 s   said         [it] Aiuto!   [en] Help!
    0.2 to   1.3 s   HELP         aiuto
    1.3 s            ALERT        help_word aiuto

thud_bag_01.wav
    0.5 to   1.0 s   thud         0.33  Thump, thud

tv_rai1_01.wav
   10.0 to  12.0 s   tv_music     0.80  Television
   40.0 to  41.0 s   HELP         help
   41.0 s            ALERT        help_word help
"""


def test_listen_output_is_scored_per_file():
    names = ["help_it_anna_01.wav", "thud_bag_01.wav", "tv_rai1_01.wav"]
    sections = detection.split_by_file(LISTEN_OUTPUT, names)
    rows = {n: detection.score(parse(Path(n)), detection.read_section(sections[n]), 60.0) for n in names}
    assert rows["help_it_anna_01.wav"]["caught"] == 1
    assert rows["thud_bag_01.wav"]["caught"] == 1 and rows["thud_bag_01.wav"]["false_alarms"] == 0
    assert rows["tv_rai1_01.wav"]["caught"] == "" and rows["tv_rai1_01.wav"]["false_alarms"] == 1   # HELP + ALERT = one alarm


# ------------------------------------------------------------------ Experiment 5 parsing

DUMPSYS = """Current Battery Service state:
  AC powered: false
  USB powered: false
  Wireless powered: false
  status: 3
  level: 87
  voltage: 4123
  temperature: 312
"""

TOP = """Tasks: 600 total
  PID USER         PR  NI VIRT  RES  SHR S[%CPU] %MEM     TIME+ ARGS
 4242 u0_a312      10 -10  14G 210M 120M S 12.5   2.7   1:02.33 app.nonnawatch.listener
  999 root         20   0  10G  10M   9M S  0.0   0.1   0:00.01 init
"""


def test_battery_and_app_cpu_are_read():
    b = battery.parse_battery(DUMPSYS)
    assert b == {"level_pct": 87, "temp_c": 31.2, "voltage_v": 4.123, "charging": False}
    assert battery.parse_top(TOP, "app.nonnawatch.listener") == 12.5
    assert battery.parse_top(TOP, "app.missing") is None


# ------------------------------------------------------------------ Experiments 2 and 7

def test_streaming_is_about_2_7_gb_per_listener_per_day():
    assert round(datavolume.streamed(1) / 1e9, 2) == 2.77


def test_edge_sends_no_audio_and_far_less_data():
    edge, cloud = datavolume.rows(3, 30, 30 * 200, "test")
    assert edge["audio_bytes_per_day"] == 0
    assert cloud["audio_bytes_per_day"] == 3 * 32_012 * 86_400
    assert cloud["bytes_per_day"] / edge["bytes_per_day"] > 10_000


# ------------------------------------------------------------------ charts from fake results

def fake_results(folder: Path) -> None:
    rng = random.Random(1)

    def write(name, fields, rows):
        with (folder / name).open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)

    t = []
    for setup, base in (("edge", 2.0), ("cloud", 3.2), ("phone", 1.4)):
        for network, extra in (("normal", 0), ("slow", 1.5 if setup == "cloud" else 0.3)):
            for n in range(30):
                rx = (0.3 if setup != "cloud" else 0.9) + extra * 0.6 + rng.random() * 0.2
                det = rx + base * 0.6 + rng.random() * 0.5
                t.append({"trial": n + 1, "setup": setup, "network": network, "status": "sent",
                          "received_s": round(rx, 1), "detected_s": round(det, 1),
                          "sent_s": round(det + 0.3 + extra * 0.4 + rng.random() * 0.3, 1)})
    write("exp1_alert_time.csv", trials.FIELDS, t)
    write("exp2_data_volume.csv", datavolume.FIELDS, datavolume.rows(3, 30, 6000, "test"))
    d = [{"file": f"help_{l}_x_{i}.wav", "kind": "help", "lang": l, "expected": "help word",
          "caught": int(rng.random() < p), "false_alarms": 0} for l, p in
         (("it", .95), ("en", .9), ("hi", .6), ("ur", .65), ("bs", .85)) for i in range(20)]
    d += [{"file": f"thud_bag_{i}.wav", "kind": "thud", "lang": "", "expected": "thud",
           "caught": int(rng.random() < .8), "false_alarms": 0} for i in range(20)]
    d += [{"file": "tv_a_1.wav", "kind": "tv", "lang": "", "expected": "nothing", "caught": "",
           "false_alarms": 2, "duration_s": 3600}]
    write("exp3_detection.csv", detection.FIELDS, d)
    w = [{"size": s, "file": f"help_{l}_{i}", "lang": l, "seconds": round(sec * (0.8 + rng.random() * .4), 3),
          "caught": int(rng.random() < p * q), "matched": ""}
         for s, sec, q in (("tiny", .3, .8), ("base", .7, .95), ("small", 2.1, 1.0))
         for l, p in (("it", 1), ("hi", .7)) for i in range(10)]
    write("exp4_whisper_sizes.csv", ["size", "file", "lang", "seconds", "caught", "matched"], w)
    start = datetime(2026, 12, 1, 10)
    b = [{"time": (start + timedelta(minutes=m)).isoformat(), "mode": mode, "level_pct": 95 - m * rate / 60,
          "app_cpu_pct": cpu} for mode, rate, cpu in (("streaming", 6, 9), ("local", 11, 31)) for m in range(0, 61, 5)]
    write("exp5_battery.csv", battery.FIELDS, b)


def test_every_chart_is_drawn(tmp_path, monkeypatch):
    results, out = tmp_path / "results", tmp_path / "charts"
    results.mkdir()
    fake_results(results)
    monkeypatch.setattr(charts, "RESULTS", results)
    monkeypatch.setattr(charts, "CHARTS", out)
    charts.main()
    made = sorted(p.name for p in out.glob("*.png"))
    assert made == ["exp1_alert_time.png", "exp1_hops.png", "exp2_data_volume.png", "exp3_detection.png",
                    "exp4_whisper_sizes.png", "exp5_battery.png", "exp6_network.png"]


def test_no_results_no_charts(tmp_path, monkeypatch):
    monkeypatch.setattr(charts, "RESULTS", tmp_path)
    monkeypatch.setattr(charts, "CHARTS", tmp_path / "charts")
    charts.main()
    assert not (tmp_path / "charts").exists()


# ------------------------------------------------------------------ review fixes (PR #3)

def test_a_trial_ignores_notices_other_rooms_and_late_alerts_from_before():
    alerts = {a.kind + a.room: a for a in hublog.parse(HUB_OUTPUT.splitlines())}
    help_word, offline = alerts["help_wordbathroom"], alerts["offlinekitchen"]
    assert trials.belongs_to_trial(help_word, "bathroom", None, "14:03:11.0")
    assert not trials.belongs_to_trial(help_word, "bathroom", None, "14:03:30.0")    # sound came before the trial
    assert not trials.belongs_to_trial(help_word, "kitchen", None, "14:03:11.0")     # another room
    assert not trials.belongs_to_trial(help_word, "bathroom", {"thud"}, "14:03:11.0")
    assert not trials.belongs_to_trial(offline, "kitchen", None, "14:04:00.0")       # a notice, not a reaction
    assert trials.belongs_to_trial(offline, "kitchen", {"offline"}, "14:04:00.0")    # unless asked for


def test_phone_clock_a_little_behind_still_counts_and_midnight_is_fine():
    a = hublog.AlertTiming(room="kitchen", at="00:00:01.0", kind="thud")
    assert trials.belongs_to_trial(a, "kitchen", None, "23:59:58.0")
    b = hublog.AlertTiming(room="kitchen", at="14:00:09.0", kind="thud")
    assert trials.belongs_to_trial(b, "kitchen", None, "14:00:10.0")                 # 1 s skew allowed


def test_waiting_skips_alerts_that_are_not_this_trials(tmp_path):
    log = tmp_path / "hub.log"
    log.write_text(HUB_OUTPUT, encoding="utf-8")
    alert, _ = trials.wait_for_alert(log, 0, hublog.HubLogReader(), 0.5,
                                     accept=lambda a: trials.belongs_to_trial(a, "bathroom", {"thud"}, "14:07:00.0"))
    assert alert.kind == "thud" and alert.sent_s == 41.9


def test_battery_chart_keeps_runs_apart_and_skips_charging(tmp_path, monkeypatch):
    monkeypatch.setattr(charts, "CHARTS", tmp_path)
    drawn = {}
    real_plot = charts.plt.Axes.plot

    def spy(ax, xs, ys, *a, **kw):
        drawn[kw.get("label")] = list(ys)
        return real_plot(ax, xs, ys, *a, **kw)

    monkeypatch.setattr(charts.plt.Axes, "plot", spy)
    rows = [{"run": run, "time": f"2026-12-0{day}T10:{m:02d}:00", "mode": "streaming", "level_pct": lvl,
             "charging": charging, "app_cpu_pct": 9}
            for run, day in (("streaming 2026-12-01T10:00", 1), ("streaming 2026-12-02T10:00", 2))
            for m, lvl, charging in ((0, 90, "False"), (30, 87, "False"), (59, 100, "True"))]
    assert charts.battery(rows) is not None
    assert drawn == {"streaming 2026-12-01T10:00": [90, 87], "streaming 2026-12-02T10:00": [90, 87]}
