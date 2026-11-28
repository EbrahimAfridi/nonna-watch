# Nonna Watch: project context for teammates and their AI assistants

Paste this whole file into your AI (Claude, ChatGPT, whatever you use) at the start of every
session, together with the latest `DECISIONS.md` from the WhatsApp group. The full requirements
document is at `docs/project-requirements.pdf`; read it once, it is the source of truth for what
the system does. This file is the source of truth for how we build it and what we have decided.

## 1. What we are building

Nonna Watch is a course project for the Mobile Computing exam. An older person living alone has
old Android phones plugged in around the house that listen for trouble (a fall, a scream, a call
for help in her own language, a broken routine). A laptop in the same house (the "edge" / "hub")
runs the AI on the audio and deletes it immediately. Only short text labels like
`{"room": "kitchen", "sound": "Water tap, faucet", "start": ..., "end": ...}` go to the cloud
(Firebase). The family gets alerts within seconds. Audio never leaves the house and is never saved.

## 2. Goal and scope rules (read these before anything else)

1. **This is a course demo, not a product.** We show the professor a basic working system where
   every feature we claim actually works. We are not building for real end users, app stores,
   or sales. Do not spend time on production concerns (scaling to thousands of homes, GDPR
   paperwork, onboarding flows, account recovery, etc.).
2. **Every claimed feature must work live.** It is better to claim fewer features that work than
   many that half work. If something cannot be made to work properly in scope, say so in the
   group instead of faking it.
3. **Spend as close to €0 as possible.** Everything is open source, Google free tier, or hardware
   we already own. If any task appears to require paying for anything (a service, a plan, a
   device, a domain), stop and raise it in the group. Nothing paid is bought or enabled without
   a group decision recorded in `DECISIONS.md`.
4. **Google only for cloud.** The course is sponsored by Google. We may use Google Cloud, Firebase,
   and any Google library. We may not use anything from Microsoft (Azure, GitHub Actions is fine)
   or Amazon (AWS). Open-source libraries from anyone are fine.
5. **UI has no restrictions.** Make it as plain or as fancy as you want, as long as the time is
   not taken from a feature that has to work.
6. **AI assistance is allowed** by the professor. Use it freely, but you are responsible for
   understanding and testing what it writes.

## 3. Final decisions so far

| # | Decision | Why |
|---|---|---|
| D1 | Both apps (listener and family) are native Android in **Kotlin**. No React Native, no Expo, no React web dashboard. | The professor's form lists Kotlin-native items (Coroutines/Flow, MVVM, Room, Notifications, unit tests, on-device NN). RN earns none of them. |
| D2 | Hub is **Python 3.12 + FastAPI**, managed with `uv`. Not 3.13/3.14. | TensorFlow (for YAMNet) does not support 3.14. |
| D3 | Sound recognition: **YAMNet** (TFLite model). Speech detection: **Silero VAD**. Help words: **faster-whisper** (`base` by default; `tiny`/`small` are experiment variants). | All free, pretrained, run on CPU. |
| D4 | **Phone-only mode runs YAMNet only, no Whisper.** It catches thuds, screams, glass, water, TV, but not help words. We report this as a finding ("the phone alone cannot do help words in 5 languages, which is why the hub exists"). | Whisper on an old Android phone means compiling whisper.cpp with the NDK and JNI glue, days of work for a result we expect to be bad. |
| D5 | **Whisper never auto-detects language.** Each home has a list of expected languages in settings. For each speech segment we run Whisper once per configured language and match help words from any result. | Language detection on a one-word shout is unreliable. |
| D6 | **Whisper runs on VAD segments, not on 1-second chunks.** Accumulate speech until VAD says it ended, then transcribe. | Transcribing 1-second slices breaks words. |
| D7 | **Firestore writes stay inside the free quota (20k writes/day).** The hub merges consecutive identical labels into one event (start/end), drops `Silence` and low-confidence frames, and writes events in batches every 1–5 minutes. Heartbeat every 5 minutes, not every minute. **Alerts are written immediately**, never batched. | 3 listeners at 1 label/second would be 260k writes/day. |
| D8 | **Detection and alerts are real-time on the hub.** The batching in D7 only delays the timeline in the cloud, never an alert. | |
| D9 | Alerts: **Telegram bot** first (Level 1), **FCM push** in the family app second (Level 2). Both stay. | Telegram is the fastest end-to-end demo and reaches the iOS teammate's phone too. |
| D10 | **Listener phones:** Ebrahim's Nothing CMF Phone 2 Pro (Android 15) and the Android teammate's phone. Any Android 8+ phone works; "old phone" in the doc just means a spare one left plugged in. There is no iOS listener. | |
| D11 | **Demo network:** a personal phone's hotspot. Laptop and listener phones join it. The listener phone is never the hotspot. No travel router. | University Wi-Fi blocks phone-to-laptop traffic. A MacBook cannot be on Wi-Fi and share Wi-Fi at the same time. |
| D12 | **Hub laptop for the demo:** any of our laptops (Mac or Windows). Needs 8 GB RAM, ~5 GB disk, CPU from ~2018 or newer. Never run the Android emulator on the same laptop as the hub; use real phones. | YAMNet uses a few % CPU; Whisper base runs ~1 s per speech segment; total RAM ~2–3 GB. Fine for hours. |
| D13 | **MEMS sensor on the form = the phone's built-in light sensor** ("lights on at 03:00" event). Nothing to buy. | |
| D14 | We do **not** force GPS, CameraX, OpenCV or ML Kit. ML Kit has no audio API. Those form boxes stay unticked. | |
| D15 | **Daily Gemini summary** is optional and last. It earns nothing on the form. | |
| D16 | **ESP32 microphone** (€12) and **travel router** (€25) are not bought unless the group decides otherwise after everything else works. | |
| D17 | **Billing: pending group decision (see section 11).** No GCP education credits exist. | |
| D18 | Repo is a **monorepo** on GitHub (see section 6). One branch per track, merged to `main` daily. `main` must always run the end-to-end demo once it first works. | |
| D19 | **No AI attribution anywhere in git.** Commit messages, PR titles, PR bodies and branch names never contain trailers or notes like `Co-Authored-By: Claude`, `Generated with Claude Code`, `Written with ChatGPT`, or any "AI helped write this" line. Many assistants add these by default at the end of a commit message; tell yours not to, and strip them if they appear. Commit messages explain why, not what. | Group preference. Applies to every teammate and every assistant. |

## 4. Architecture

```
Inside the house (audio never leaves)
  Listener phone(s)  --audio 1 s chunks, WebSocket over Wi-Fi-->  Hub laptop (FastAPI)
  Listener phone(s)  <--"ask: are you okay?" command-----------  Hub
  Hub: YAMNet every second -> Silero VAD -> faster-whisper on speech -> detection rules
       keeps a few seconds of audio in RAM, then discards it. Never written to disk.

Leaving the house (labels and alerts only, ~150 bytes each)
  Hub  --batched events, heartbeat, alerts-->  Firestore
  Hub  --instant alert-->  Telegram bot API
  Firestore  <--settings (help words, languages, contacts)--  Family app
  Cloud Functions + Scheduler (or a hub loop, see section 11): routine check, long-silence
       check, listener-offline check -> alerts -> FCM push to family app
  Cloud Run (Milan, europe-west8): same hub container, used only for the edge-vs-cloud experiment
```

### Event written to Firestore

```json
{"home": "maria", "room": "kitchen", "sound": "Water tap, faucet",
 "confidence": 0.91, "start": "2026-11-25T08:05:12+01:00", "end": "2026-11-25T08:05:40+01:00"}
```

### Firestore collections

- `homes/{homeId}`: name, timezone, languages, helpWords (per language, including script
  variants, e.g. `bachao`, `बचाओ`, `بچاؤ`, `upomoc`, `upomoć`), familyContacts, telegramChatId
- `homes/{homeId}/devices/{deviceId}`: room, lastHeartbeat, online
- `homes/{homeId}/events/{eventId}`: room, sound, confidence, start, end
- `homes/{homeId}/alerts/{alertId}`: type, room, time, status (`sent`, `seen`, `resolved`),
  answeredBy, followUp
- `homes/{homeId}/routines/{room_sound}`: usual time window, frequency, learned from history

Security rules: a signed-in family member can read/write only the homes they are a member of.

### Detection rules (all thresholds are settings)

| Hub hears | Voice check first? | Result |
|---|---|---|
| Help word in a configured language | No | Alert at once; voice check runs in parallel; follow-up "she says she's okay" if she answers |
| Screaming or crying | No | Same |
| Heavy thud, then 10 s silence | Yes | No answer in 30 s, or "help": alert |
| Glass breaking | Yes | Same |
| No sound for 45 min at a usually-active time | Yes | No answer: alert |
| Routine missing (no kitchen sounds by 11:00) | Yes | No answer: alert |
| No heartbeat from a listener for 5 min | No | "Kitchen listener offline" |
| Smoke alarm (extra) | No | Alert at once |
| Water running 20+ min (extra) | No | Gentle notice |

## 5. Tech stack (all free)

| Part | Tool |
|---|---|
| Listener app | Kotlin, `AudioRecord` 16 kHz mono 16-bit, foreground service (type `microphone`), OkHttp WebSocket, Canvas mic-level view, light sensor, Room buffer, Coroutines/Flow, MVVM |
| Family app | Kotlin, Firebase Auth (Google Sign-In), Firestore snapshots as Flow, FCM push with "Call Maria / Call neighbour / Call 112" actions, timeline chart on Canvas, settings, Room cache, MVVM, unit tests |
| Phone-only mode | MediaPipe Audio Classifier (default model is YAMNet) via LiteRT, inside the listener app behind a "target: hub / cloud / local" setting |
| Hub | Python 3.12, FastAPI, `websockets`, YAMNet TFLite, `silero-vad`, `faster-whisper`, `firebase-admin`, `python-telegram-bot` or raw HTTP |
| Cloud | Firebase (Firestore, Auth, FCM, Hosting if needed), Cloud Functions + Cloud Scheduler, Cloud Run, Terraform (only if billing exists, see section 11) |
| Experiments | Python scripts, CSV results, matplotlib charts; `tc netem` (Linux), Network Link Conditioner (Mac), `clumsy` (Windows); ESC-50 dataset + our own recordings |

## 6. Repository layout

```
nonna-watch/
  CONTEXT.md              this file
  DECISIONS.md            gitignored, shared via WhatsApp (see section 12)
  README.md               how to run each part in 15 minutes
  docs/                   requirements PDF, API contract, schema, slides later
  hub/                    Python hub (uv project)
  android/                one Gradle project: :listener, :family, :core modules
  cloud/                  functions/, terraform/, seed scripts
  experiments/            harness scripts, raw CSVs, charts
```

## 7. Team and ownership

| Person | Track | Owns |
|---|---|---|
| Ebrahim (Mac, Nothing phone) | Edge AI + integration | `hub/`: YAMNet, VAD, Whisper, detection rules, event merger, Firestore sync, Telegram, voice-check hub side. Integrator: the hub is the centre, so Ebrahim merges and runs the full-system tests. |
| Teammate A (Android phone, Windows) | Android | `android/`: listener app, then family app, then phone-only mode. |
| Teammate B (iPhone, Windows) | Cloud + experiments | `cloud/` and `experiments/`: Firebase project, Telegram bot, routine/offline checks, Cloud Run, Terraform, test-set recordings, experiment harness, charts, slides. |

B needs no Android phone; experiments run on Ebrahim's and A's phones.

## 8. Ordered task list

No dates. Do the tasks in your track in order; each one is a working demo by itself. The
integration milestones are the points where tracks must meet. Work ahead if you are fast; the
only hard rule is that a milestone is not "done" until the test for it passes on `main`.

### Shared first (whoever gets there first, in `docs/`)

- S1. Done: `docs/api-contract.md` (protocol 1). Hub WebSocket + REST contract: `hello` /
  `welcome`, binary audio frames, `heartbeat`, `light`, `ask` / `ask_played`, `set_paused`,
  `checkin_clip`, REST `/health`, `/devices`, `/ask`. A codes against it.
- S2. Firestore schema and security rules written down (`docs/firestore-schema.md`). B writes it;
  Ebrahim and A code against it.

### Track: Edge AI (Ebrahim)

- E1. Done: `hub/` uv project, Python 3.12. `uv run nonna-hub listen [FILE ...]` prints YAMNet's
  top labels every 0.5 s from the laptop mic or from audio files (see `hub/README.md`).
- E2. Done: `hub/nonna_hub/categories.py` groups YAMNet labels into 19 household categories (safety:
  scream, distress, thud, glass, smoke_alarm); `events.py` merges windows into events, and more than
  1 s without the sound ends one. `listen` and `serve` print events; `listen --raw` prints labels.
  On 105 ESC-50 clips glass was 3/3 with no false alarm in 34 other classes. ESC-50 has no scream,
  fall or smoke alarm, so those need our own recordings.
- E3. Silero VAD → speech segment → faster-whisper per configured language → normalised help-word
  match → prints `HELP`. Done: `speech.py` and `help_words.py`; `listen` and `serve` take
  `--languages it,en,...`. Checked with the Mac's Italian, English, Hindi and Croatian voices,
  through fake phones to the real server: every help phrase caught, "helpful" ignored. Default
  help words and the Hindi/Urdu script rule are D24; only help phrases are shown (D25).
- E4. FastAPI WebSocket server: accepts N phones, each registered with a room; runs E1–E3 on the
  incoming stream instead of the laptop mic. Audio stays in RAM only, a few seconds at most.
  Done: `nonna-hub serve` implements docs/api-contract.md and runs the events (E2) and help words
  (E3) on each phone's stream; `nonna-hub fake-phone` streams files or the laptop mic like a
  phone, so A can test against a real hub.
- E5. Detection rules (help word, scream, thud + 10 s silence, glass) → Telegram alert with
  room + time. Timestamp log at every hop (captured / hub received / AI done / alert sent).
  Done: `rules.py` (plus crying and smoke alarm from the table in section 4) and `telegram.py`;
  `serve` prints each alert with its hops and sends it to Telegram; `telegram-test` checks the
  bot and finds the group's chat id. Since E7, thud and glass ask first (D26, D27).
- E6. Firestore sync: batched events every 1–5 min, heartbeat every 5 min, alerts immediately.
  Offline queue: if internet drops, keep working and flush later.
- E7. Voice check hub side: send `ask` to the phone, listen 30 s for "fine"-words or help words,
  alert on silence or help, follow-up message if she answers after an instant alert.
  Done: `voice_check.py` and the flow in `server.py`, as the table in section 4 says. Speech
  while the question plays is ignored; any negation ("non sto bene") never counts as fine; the
  question is asked in the home's first language (D27). Checked through a fake phone: "aiuto" →
  alert → "Stai bene?" → "sì, sto bene" → follow-up.
- E8. Multi-room, smoke alarm, long-running water; hub config from `homes/{id}` settings.
  Done except the config: one listener per room (E4), smoke alarm (E5), and a gentle notice
  after 20 min of running water. Left: read languages, help words and the question from
  `homes/{id}` once E6 exists.
- E9. If no billing (section 11): the routine / long-silence / offline checks as a 15-minute loop
  inside the hub, using B's logic. Offline done, in either billing path: a room that sends nothing
  for 5 min alerts once, and again when it is back (D29). Left: routine and long silence (C5).
- E10. Dockerfile for the hub so B can deploy the identical image to Cloud Run. Done:
  `hub/Dockerfile`, with YAMNet and Whisper inside so a cold start downloads nothing; settings
  through environment variables; deploy notes in `hub/README.md`.

### Track: Android (A)

- A1. Android Studio, Gradle project with `:core`, `:listener`, `:family`. MVVM skeleton.
- A2. Listener: foreground service (`foregroundServiceType="microphone"`,
  `FOREGROUND_SERVICE_MICROPHONE`), `AudioRecord` 16 kHz mono, audio as `Flow<ShortArray>`.
  Partial `WakeLock` + `WifiLock`. Document the "set battery to Unrestricted" step.
- A3. WebSocket client (OkHttp) streaming 1 s chunks per the contract; room name in settings;
  reconnect loop with backoff; heartbeat.
- A4. Canvas mic-level / waveform view (2D graphics box). Light sensor → "light on/off" event
  (MEMS sensor box).
- A5. Room buffer: when the hub is unreachable, store local events and flush on reconnect.
- A6. Play the "Are you okay?" clip when the hub sends `ask`; report back.
- A7. Family app: Google Sign-In, home selection, today's timeline from Firestore snapshots as
  Flow, alerts list with status, settings screen (help words per language, languages, contacts).
- A8. FCM push: notification channel, "Call Maria / Call neighbour / Call 112" actions, mark
  alert seen/resolved. Record and upload the check-in clip.
- A9. Timeline chart on Canvas; Room cache of the timeline for offline viewing.
- A10. Phone-only mode: MediaPipe Audio Classifier (YAMNet) on device, same detection rules for
  thud/scream/glass, alerts written to Firestore directly. "Target" setting: hub / cloud / local.
- A11. Unit tests for ViewModels and any rule logic that lives on the phone.

### Track: Cloud + experiments (B)

- C1. Firebase project (Spark for now). Firestore, Auth with Google provider, FCM enabled.
  `google-services.json` and a service-account key shared privately (never committed).
- C2. Telegram bot via BotFather; family group; bot can post to it. Add the professor to the
  group for the demo.
- C3. Firestore schema + security rules (S2), rules unit tests with the Firebase emulator.
- C4. Seed script: 14 days of realistic fake events for a home, for the routine layer and demos.
- C5. Routine learner + checks: per room/sound/hour expected activity from history; "missing
  routine", "long silence at active time", "listener offline > 5 min". As Cloud Functions on a
  15-minute Cloud Scheduler if billing exists; otherwise as a Python module Ebrahim runs in the
  hub (E9). Write the logic so it runs in both places.
- C6. Test set: 20 bag-drop thuds, 20 help words per language from real people (Italian,
  English, Hindi, Urdu, Bosnian), everyday kitchen sounds, 1–2 h of TV/radio, ESC-50 clips.
  Store outside the repo (big), share a link.
- C7. Experiment harness: timing CSV from the hop timestamps, bytes-out counter, battery logger
  (`adb shell dumpsys battery`), CPU logger, 30-trial runner. Charts generated by script.
- C8. If billing exists: Cloud Run deploy of the hub image in `europe-west8`, `min-instances=0`,
  `max-instances=3`; Terraform for Cloud Run, Artifact Registry, Scheduler, Firestore.
- C9. Run the 7 experiments (requirements PDF, "Experiments"), 30 trials each, on edge / cloud /
  phone-only. Slow network via netem / Link Conditioner / clumsy. Load test with ~30 fake
  clients against Cloud Run to show autoscaling.
- C10. Slides, README polish, demo script.

### Integration milestones (in order)

- **M1 "Hub hears":** E1–E3 pass on the laptop mic. (Ebrahim alone.)
- **M2 "Phone streams":** A3 + E4: phone in another room, hub prints labels with the room name.
  Kill Wi-Fi for a minute, restore, it reconnects. 1 hour on charge with screen off, service
  survives.
- **M3 "First alert" (basic prototype, tag `v1-basic`):** E5 + C2: shout "aiuto" at the phone, a
  Telegram message appears on another phone within seconds. Timestamps logged at every hop.
- **M4 "Timeline":** E6 + A7 + C3: events appear in the family app ~1 s after the hub console;
  Firestore usage shows well under 20k writes/day; a second Google account cannot read the home.
- **M5 "Voice check":** E7 + A6: drop a bag, stay silent → alert after 30 s. Drop a bag, say
  "sto bene" → no alert, event logged.
- **M6 "Routine":** C4 + C5 (+ E9): seed history, simulate 11:00 with no kitchen events → alert.
  Unplug a phone → "Kitchen listener offline" within 5 min.
- **M7 "Three targets":** E10 + A10 + C8: the same shout produces an alert via hub, via Cloud Run,
  and via phone-only (phone-only: a scream or thud, since it has no Whisper).
- **M8 "Feature complete":** code freeze except bug fixes. Everything after this is C9–C10 and
  rehearsal.

## 9. How we test each piece

- Hub rules and the event merger: unit tests with synthetic label sequences (this is where a
  silent bug produces a wrong alert, so test it properly).
- Help words: 5 people × 5 languages, plus 10 minutes of TV with zero false `HELP`.
- Listener: the M2 checklist above (other room, Wi-Fi cut, 1 hour screen-off).
- Firestore rules: emulator tests, plus the "second account cannot read" manual check.
- Routine checks: emulator run against seeded history with a faked clock.
- End to end: the M3 and M5 scripts, rehearsed on a hotspot in a room we do not control.
- Experiments: 30 trials each, average and worst case, raw CSVs committed, charts from scripts,
  never by hand.

## 10. Cut list, in this order, if we run out of time

1. Terraform
2. Phone-only mode (Experiment 5 becomes "streaming only")
3. Smoke alarm / long-water extras
4. Experiments 6 and 7 (keep 1–4)
5. Routine layer

Never cut: Telegram alert, timeline, voice check, Experiment 1.

## 11. Open decision: billing (Path A or Path B)

There are no GCP education credits. Google Cloud (Cloud Run, Functions, Scheduler, Storage) and
Firebase Blaze all need a billing account to exist, even for the free tier.

- **Path A: Google Cloud free trial.** One teammate's card, $300 / 90 days, Google cannot charge
  a trial account; it suspends instead. Everything we use is inside the permanent free tier
  anyway, so real spend ≈ €0. Guardrails: budget alerts at €1 and €5, Cloud Run
  `min-instances=0` / `max-instances=3`, delete Cloud Run and Scheduler after the presentation,
  never click "Activate full account". Keeps every form checkbox and the cloud leg of Experiment 1.
- **Path B: Spark plan only, no card.** Routine/offline checks run inside the hub (E9), the
  check-in clip is stored as base64 in Firestore or replaced by Android TextToSpeech, Cloud Run
  is dropped (Experiment 1 becomes edge vs phone-only), and the Serverless / Container /
  Autoscaling / Load Balancer / Terraform boxes stay unticked.

Recommendation on the table: Path A. Until the group decides, build as if Path B; everything up
to M6 is identical in both paths.

## 12. `DECISIONS.md`: keeping everyone's AI in sync

Three people, three AI assistants. To avoid redundant or diverging work:

- `DECISIONS.md` lives at the repo root and is **gitignored**. It is shared as a file in the
  WhatsApp group whenever it changes; the newest copy in the group is the truth.
- Whenever you or your AI make a decision that another track could depend on (an API message
  shape, a Firestore field, a library choice, a threshold, a thing we will not do), append an
  entry and post the file. Also append when a decision in this file is overturned.
- Entry format: `D<number> | <date> | <who> | <decision> | <why> | <what it affects>`.
- Before starting a session, give your AI this `CONTEXT.md` plus the latest `DECISIONS.md`, and
  tell it which track and which task number you are on.
- Anything paid, any new external service, any change to the API contract or schema: discuss in
  the group first, then record it. Do not let an AI "helpfully" add a paid service.

## 13. Working agreements

- Branch per track (`edge`, `android`, `cloud`), merge to `main` at least daily via PR; the
  author merges their own PR after a quick self-review.
- Contracts before code: S1 and S2 exist before anyone writes a client against them.
- Secrets (`google-services.json`, service-account keys, Telegram token, `.env`) are never
  committed. They are gitignored and shared privately.
- Short daily message in the group: what you merged, what you are blocked on.
- When your AI generates code, read it and run its test before pushing. Do not push code you
  cannot explain.
- Before every commit, check the message has no AI trailer (see D19). If your assistant writes
  the commit message, read the last lines before you accept it.

## 14. Known gotchas (so your AI does not rediscover them)

- Android 14+ requires `foregroundServiceType="microphone"` plus `FOREGROUND_SERVICE_MICROPHONE`
  for background recording. OEMs (Xiaomi, Samsung, Nothing) kill services unless battery is set
  to "Unrestricted".
- Firestore free quota is 20k writes/day. See D7.
- Cloud Run cold start with YAMNet + Whisper is 10–30 s. Run experiment trials against a warm
  instance and report cold start separately.
- Whisper hallucinates on short noisy clips. Only run it on VAD-detected speech, require a clear
  help-word match, and rely on the voice check to catch mistakes.
- Help word timing: VAD end-of-speech + Whisper + network is realistically 2–5 s on the edge.
  Say "within seconds"; let Experiment 1 give the number.
- YAMNet works on ~0.975 s windows; keep a rolling buffer rather than classifying exactly one
  chunk at a time.
- Python 3.14 does not run TensorFlow. Pin 3.12 with `uv`.
- faster-whisper 1.2.1 cannot load audio files with PyAV 19 (`unexpected keyword argument
  'metadata_errors'`). `hub/pyproject.toml` pins `av<17`; keep the pin.
- Whisper writes spoken Hindi in Devanagari or Urdu script whichever of `hi` / `ur` it is told
  (a Hindi "बचाओ" came back as "بچاو"), so both help-word lists hold both scripts (D24).
- Whisper `base` is unreliable for Hindi: the same "बचाओ" clip came back as "بچاو", "بَجَو" or
  "BAJAU" depending on a few milliseconds of silence around it, and मदद as "मदख". Italian, English
  and Bosnian were reliable. The English pass often translates other languages ("Upomoć!" →
  "Help! Help!"), which catches some. Compare `small` for Hindi homes in the experiments.
- Help words also match ordinary sentences ("grazie per l'aiuto", "can I help you?"), from people
  or the TV. The 10-minute TV test (section 9) decides whether we add a rule such as "short phrases
  only", which would also miss "help, I fell and can't get up".
- Whisper's default retries unsure phrases at a higher temperature, which samples at random, so the
  same audio gave different words on each run. The hub uses beam search at temperature 0: the same
  audio always gives the same words.
- Whisper's first download is 141 MB from Hugging Face and took 9 minutes; do it before the demo,
  never on the hotspot. Afterwards it loads offline in under a second.
- The hub needs about 0.5 GB of RAM with Whisper. An 8 GB laptop with a browser and an IDE open was
  already swapping 7 GB, so close other apps on the demo laptop.
- YAMNet labels real clips loosely: rain scores `Water` 0.98, normal breathing `Gasp` 0.67, a
  creaking door `Crying, sobbing` 0.85, a vacuum cleaner `Jet engine`. `hub/nonna_hub/categories.py`
  says which labels were left out and why; tune its thresholds on our own phone recordings.
- Streaming 16 kHz 16-bit mono is 32 KB/s ≈ 2.76 GB/day per listener. That number is the
  privacy and bandwidth argument for the edge; measure it in Experiment 2.
- Citations in the requirements dated 2026 (WHO 842,000, Raspberry Pi $85, ISTAT Feb 2026)
  should be re-verified before the slides.

## 15. Professor's form: what we tick and how

| Form item | How |
|---|---|
| MEMS sensors | Light sensor in the listener |
| 2D graphics | Canvas mic-level view; Canvas timeline chart |
| Notifications | FCM push with call actions |
| Coroutines/Flow | Audio pipeline and Firestore snapshots as Flow |
| REST API or similar | Hub REST endpoints, Firestore, Telegram API |
| on-device NN model | YAMNet via MediaPipe / LiteRT in phone-only mode |
| Local DB (Room) | Listener offline buffer; family timeline cache |
| External cloud storage | Firestore (+ Cloud Storage under Path A) |
| MVVM, unit tests | Both apps; tests on rules, merger, ViewModels |
| Firebase, Authentication, Database | Firestore, Google Sign-In, security rules |
| Serverless | Cloud Functions + Scheduler (Path A only) |
| VM/Container, Autoscaling, Load Balancer | Cloud Run (Path A only); load test shows scaling |
| Terraform | Cloud pieces as Terraform (Path A only, last) |
| GPS, CameraX, OpenCV, ML Kit | Not used |
