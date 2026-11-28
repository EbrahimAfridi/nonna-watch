# experiments/: measuring Nonna Watch (Track B, C7 and C9)

The requirements ask for 7 experiments on three setups: **edge** (the laptop hub), **cloud** (the same hub
on Cloud Run in Milan) and **phone-only** (YAMNet on the phone). Each runs **at least 30 times**, and we report
the **average and the worst case**. This folder has the tools that measure, the raw results, and the charts.

| Folder | What's in it | In git? |
|---|---|---|
| `src/nonna_exp/` | The measuring tools (below) | yes |
| `tests/` | Tests for the tools, with hub output in its exact format | yes |
| `results/` | Raw results, one CSV per experiment | **yes**: the raw numbers are part of the report |
| `charts/` | PNG charts, made by `charts.py` from the CSVs, never by hand | yes |
| `data/` | Test recordings (C6) | **no**: too big, shared by link |
| `hub.log` | The hub's output during a run | no |

## Setup (once, about 5 minutes)

```powershell
cd experiments
uv sync                      # Python libraries: matplotlib (charts), psutil (CPU)
uv run pytest                # 17 tests, all should pass
```
Experiment 4 also needs Whisper: `uv sync --extra whisper` (a big download). Experiment 5 needs `adb`, which
comes with Android Studio (`platform-tools` folder). The hub itself is set up as in [hub/README.md](../hub/README.md).

## The tools

| Tool | What it does |
|---|---|
| `record_hub` | Starts the hub and saves everything it prints to `hub.log` (UTF-8), while still showing it. |
| `hublog` | Reads `hub.log` and pulls out each alert's timing (the hub prints them already, see below). |
| `trials` | Runs an experiment 30 times. Either automatic (plays a recording through the hub's fake phone) or by hand (tells you when to shout at a real phone). One CSV row per trial. |
| `cpu` | Logs the hub's CPU and memory on the laptop. |
| `battery` | Logs a phone's battery, temperature and the app's CPU over adb. |
| `datavolume` | How much data leaves the house: streamed audio vs labels only. |
| `testset` | The naming rules for recordings, so scripts know what each file should trigger. |
| `detection` | Runs the hub over all recordings and scores what it caught and its false alarms. |
| `whisper_sizes` | Whisper tiny vs base vs small on the help-word recordings: speed vs caught. |
| `charts` | Every CSV in `results/` → a PNG in `charts/`. |

Run any of them with `uv run python -m nonna_exp.<tool> --help`.

## How timing works (Experiments 1 and 6)

The hub already logs every hop, timed from the moment the phone **captured** the sound:

```
bathroom     14:03:12.5   ALERT        help_word aiuto   received +0.3 s, detected +1.8 s
bathroom     14:03:12.5   SENT         +2.1 s after the sound
```

- **received** = the audio reached the hub (Wi-Fi, or the internet for Cloud Run)
- **detected** = the AI decided it's an alert
- **sent** = Telegram accepted the message

Two things to know:
1. **Clocks must agree.** "Captured" comes from the phone's clock and the rest from the laptop's. Turn on
   automatic time (NTP) on both before a run.
2. **The last hop is not logged**: Telegram delivering to the family's phone. It's usually well under a
   second. To measure it, film both screens for a few trials, or let the family app record `alertReceivedMs`
   (FCM, A8). Say in the report which one we did.

## The 7 experiments

| # | Question | Tool | Needs | Who / when |
|---|---|---|---|---|
| 1 | How fast does the family hear about a fall? | `trials` (+ `charts`) | hub running; a real phone or a recording | when the hub + listener work (M3) |
| 2 | How much data leaves the house? | `datavolume` | nothing (formula), or a real day in Firestore | **can run now** |
| 3 | How good is the detection? | `detection` | the test recordings (C6) | after C6 |
| 4 | Which Whisper size is enough? | `whisper_sizes` | help-word recordings (C6) | after C6 |
| 5 | What does it cost the phone? | `battery` | a phone with the listener app, adb over Wi-Fi | when the listener app + phone-only mode work (A10) |
| 6 | What happens on a bad network? | `trials --network slow` | as Exp. 1, plus clumsy (Windows) to slow the network | with Exp. 1 |
| 7 | How private is it? | `datavolume` (the raw-audio column) | nothing | **can run now** |

### 1. Alert speed: edge vs cloud vs phone-only
```powershell
# terminal 1
uv run python -m nonna_exp.record_hub
# terminal 2: automatic, 30 times, one recording through the fake phone
uv run python -m nonna_exp.trials --setup edge --clip data/help_it_anna_01.wav --room kitchen --kind help_word
# or by hand with a real phone
uv run python -m nonna_exp.trials --setup edge --label "real phone, shout aiuto"
```
For **cloud**, point the fake phone at Cloud Run: `--setup cloud --hub-url wss://<url>/ws/listener` (after C8).
For **phone-only**, the phone itself raises the alert (A10) and writes `timings` into the alert in Firestore,
so those rows come from Firestore, not `hub.log`. That reader is added once A10 exists.
Each trial only counts an alert from its own room (and `--kind`, if given) for a sound made after the trial
started, so a late alert from the trial before, or a phone going offline, is never timed by mistake.
Trials are 65 s apart, because the hub sends at most one alert of each kind per room per minute.

### 2 and 7. Data leaving the house
```powershell
uv run python -m nonna_exp.datavolume --listeners 3
uv run python -m nonna_exp.datavolume --listeners 3 --from-firestore --day 2026-12-01   # a real day
```
Streaming is fixed by the protocol: 32,012 bytes per second per listener, about **2.77 GB a day**. Labels are a
few hundred KB at most. Raw audio leaving the house: all of it for cloud, **none** for edge (Experiment 7).

### 3. Detection quality
Recordings go in `data/`, named by the rules in `src/nonna_exp/testset.py`:
`help_it_anna_03.wav`, `thud_bag_07.wav`, `glass_esc50_12.wav`, `kitchen_tap_04.wav`, `tv_rai1_01.wav`, ...
```powershell
uv run python -m nonna_exp.detection data/*.wav --languages it,en,hi,ur,bs
```
Gives the share of real events caught (per kind, and per language for help words) and **false alarms per
hour** of TV and radio.

### 4. Whisper sizes
```powershell
uv run python -m nonna_exp.whisper_sizes data/help_*.wav --sizes tiny,base,small
```
Same settings as the hub, and the hub's own help-word matching, so the numbers mean the same thing.

### 5. Phone battery (one hour each, phone unplugged)
```powershell
adb tcpip 5555 ; adb connect <phone-ip>:5555     # then unplug the cable
uv run python -m nonna_exp.battery --mode streaming --minutes 60
uv run python -m nonna_exp.battery --mode local --minutes 60
```
Start both runs at a similar battery level, screen off, same room temperature.

### 6. Bad network
Install **clumsy** (free, Windows), set "Lag" (e.g. 300 ms) and "Drop" (e.g. 5%) on the laptop, then repeat
Experiment 1 with `--network slow`. Both runs go into the same CSV, and `charts` draws them side by side.

### Laptop CPU (asked for in the requirements: "laptop CPU")
```powershell
uv run python -m nonna_exp.cpu --minutes 10 --label "3 listeners"
```

## Making the charts
```powershell
uv run python -m nonna_exp.charts
```
It draws every chart whose CSV exists. Colours are fixed per setup in every chart (edge blue, cloud orange,
phone-only aqua) and checked for colour-blind readers; every value is also written on the chart.
