# cloud/: Firebase, Telegram, fake history, routine checks (Track B)

This folder is the **cloud side** of Nonna Watch: everything that lives in Firebase, plus the scripts
that fill it and check it. The hub (Ebrahim) and the apps (A) code against
[docs/firestore-schema.md](../docs/firestore-schema.md); this folder makes Firestore enforce it.

## What is in here

| Path | What it is | Task |
|---|---|---|
| `firestore.rules` | Security rules: who may read and write what in Firestore. | C3 |
| `tests/rules/` | Tests for those rules. They run in a local emulator, not the real project. | C3 |
| `firebase.json`, `.firebaserc`, `firestore.indexes.json` | Config for the Firebase CLI: where the rules are, emulator ports, query indexes. | C1/C3 |
| `src/nonna_cloud/seed.py` | Writes 14 days of fake history for Maria. | C4 |
| `src/nonna_cloud/defaults.py` | Maria's home document: settings, help and fine words in 5 languages (exactly D24, D27). | C4 |
| `src/nonna_cloud/events.py` | What one sound event looks like in Firestore (one document per event, decision D30). | C4/C5 |
| `src/nonna_cloud/db.py` | Connects Python to the emulator or to the real Firestore. | |
| `src/nonna_cloud/telegram_setup.py` | Finds the family group's chat id and sends a test message. | C2 |
| `src/nonna_cloud/routine.py` | Learns Maria's usual day and decides: routine missing? long silence? hub offline? Pure logic, no database. | C5 |
| `src/nonna_cloud/checks.py` | Runs those checks against Firestore and writes alerts. Imported by the hub, or run from the command line. | C5 |
| `tests/test_seed.py` | Tests for the fake-history generator. | C4 |
| `tests/test_routine.py` | Tests for the routine checks, with a fake clock. | C5 |
| `secrets/` | **Not in git.** You create it: service-account key, bot token. | C1/C2 |

Two languages live here, for a reason:
- **JavaScript (Node)** only for the rules tests and the Firebase CLI, because Google's rules-testing
  library exists only for JavaScript.
- **Python** for everything else, so Ebrahim's hub can import the same code (the routine checks in C5
  must run both in the hub and as a Cloud Function).

## One-time install (about 10 minutes)

You need **Node.js LTS**, **Java 21** (the emulator runs on Java) and **uv** (the team's Python tool).
On Windows:

```powershell
winget install OpenJS.NodeJS.LTS
winget install astral-sh.uv
# Java: if `java -version` fails, install it with: winget install EclipseAdoptium.Temurin.21.JDK
```

Close and reopen the terminal, so it picks up the new programs, then:

```powershell
cd cloud
npm install        # Firebase CLI + rules-testing library, into cloud/node_modules (not committed)
uv sync            # Python 3.12 + libraries, into cloud/.venv (not committed)
```

## Run the tests

```powershell
npm run test:rules   # starts a throwaway Firestore emulator, runs 44 rules tests, stops it
uv run pytest        # seed + routine tests (35), no emulator needed
```

**Why an emulator:** it's a copy of Firestore running on your laptop. It's free, it needs no internet,
and tests can wipe it between runs. The project id `demo-nonna-watch` starts with `demo-`, which
tells Firebase tools that this project only exists locally, so nothing can accidentally reach the real one.

## Play with the data locally

```powershell
npm run emulators                       # terminal 1: emulator + web UI at http://127.0.0.1:4000
uv run python -m nonna_cloud.seed --emulator --member you@gmail.com --with-devices   # terminal 2
```

Open http://127.0.0.1:4000/firestore and click through `homes/maria/events`. The emulator forgets
everything when you stop it (Ctrl+C).

---

## C1: create the Firebase project (only you can do this, about 30 minutes)

Free Spark plan, so no card is needed. Do it with the Google account the team will share.

1. **Create the project.** (Done: project ID **`nonna-watch-team`**, Firestore in `europe-west8`, Spark plan.) Go to https://console.firebase.google.com → *Create a project* → name it
   `nonna-watch`. Turn **Google Analytics off** (we don't need it). Write down the **project ID** that is
   shown, e.g. `nonna-watch-1a2b3`.
2. **Firestore.** *Build → Firestore Database → Create database*.
   - Location: **`europe-west8` (Milan)**. This can **never be changed later**, and Milan is where the
     Cloud Run copy will run, so the edge-vs-cloud experiment is fair.
   - Mode: **production mode** (everything locked). Our rules open exactly what is needed in step 7.
3. **Google Sign-In.** *Build → Authentication → Get started → Sign-in method → Google → Enable*.
   Pick a support email, then save.
4. **Android apps** (do this together with A). *Project settings (gear) → Your apps → Add app → Android*.
   - Package name: ask A (for example `com.nonnawatch.family`). Add the listener app the same way.
   - **SHA-1 fingerprint:** Google Sign-In does not work without it. A gets it from Android Studio
     (`gradlew signingReport`) on the machine that builds the app. Each teammate who builds the app adds theirs.
   - Download **`google-services.json`** and send it to A **privately** (direct message, not a group).
     It goes in the app folder and is gitignored.
5. **Push notifications (FCM).** Nothing to switch on: *Project settings → Cloud Messaging* should
   show "Firebase Cloud Messaging API (V1): Enabled". If it says disabled, click to enable it.
6. **Service-account key** (this is how the hub and our scripts log in as "admin").
   *Project settings → Service accounts → Generate new private key*. Save it as
   **`cloud/secrets/service-account.json`** (create the `secrets` folder; git ignores it).
   Send it to Ebrahim privately. **Treat it like a password:** anyone with it can read and delete
   everything. If it ever leaks, delete the key on the same page and generate a new one.
7. **Upload our rules and indexes** (from `cloud/`):
   ```powershell
   npx firebase login
   npx firebase deploy --only firestore:rules,firestore:indexes --project live
   ```
8. **Add the team.** *Project settings → Users and permissions → Add member*: Ebrahim and A as **Editor**.
9. **Check it end to end** with the real project:
   ```powershell
   uv run python -m nonna_cloud.seed --member your.email@gmail.com --telegram-chat-id CHAT_ID_FROM_C2
   ```
   Then look at *Firestore Database* in the console: `homes/maria/events` with about 410 events
   (one document per event, decision D30).
10. Post the **project ID** in the group and record it in `DECISIONS.md`.

## C2: Telegram bot and family group (only you can do this, about 15 minutes)

1. In Telegram, open **@BotFather** → send `/newbot` → name: `Nonna Watch` → username: anything
   ending in `bot`, e.g. `nonna_watch_demo_bot`. BotFather replies with a **token** like `123456:ABC...`.
2. Save it in **`cloud/secrets/telegram.env`** as one line: `TELEGRAM_BOT_TOKEN=123456:ABC...`.
   Send it to Ebrahim privately; the hub sends the instant alerts.
3. Create a Telegram **group** called `Nonna Watch – family`, add the team, then add the bot by its username.
4. In the group, send `/start@your_bot_username`, so the bot "sees" the group.
5. From `cloud/`: `uv run python -m nonna_cloud.telegram_setup chat-id`. The group's id is the
   **negative** number, e.g. `-1001234567890`.
6. Test: `uv run python -m nonna_cloud.telegram_setup test -1001234567890`. A message should appear in the group.
7. Store the chat id in the home: step 9 of C1 (`--telegram-chat-id`), or edit `telegramChatId` in the console.
8. **Before the demo:** add the professor to the group.

---

## C5: routine, silence and offline checks

**What it does.** Every 15 minutes it compares today with Maria's usual day:

| Check | Fires when | Voice check first? |
|---|---|---|
| Routine missing | A room she is in every morning (e.g. the kitchen) has had no sound today, and it's past the latest normal time plus 30 minutes of grace. | Yes |
| Long silence | No sound anywhere for 45 minutes, during hours when she is usually active. | Yes |
| Hub offline | The hub itself stopped sending heartbeats for 10 minutes. Only the cloud can notice this, so it matters when the check runs in the cloud (Path A). | No |

A silent **listener phone** is not checked here: the hub already holds every phone's connection and alerts
after 5 minutes itself (decision D29).

**How it learns "usual".** Once a day it reads the last 14 days of events. For each room, and each
room+category (the hub's `water`, `cooking`, `door`, ...), it notes which hours of the day usually have activity and what time the first sound of the day
usually is. The TV, radio and music are ignored for this, because they can play with nobody there. The result
is saved in `homes/maria/routines`, so the family app can show it too.

**Why two files.** `routine.py` only does the thinking: data in, findings out, no database and no clock.
That makes it easy to test with a fake clock, and lets the *same* code run in three places: Ebrahim's hub
(E9, Path B), a Cloud Function (Path A), and the tests. `checks.py` is the thin layer that reads Firestore and
writes alerts.

**Each problem is reported once.** Alert ids are built from the problem, e.g. `routine_missing_kitchen_2026-11-27`.
A second run finds the alert already exists and stays quiet.

**Run it:**
```powershell
uv run python -m nonna_cloud.checks                  # check now; print, write nothing
uv run python -m nonna_cloud.checks --now 10:30      # fake clock
uv run python -m nonna_cloud.checks --report         # also write alerts
uv run python -m nonna_cloud.checks --report --telegram --loop   # the real thing, every 15 minutes
```

**The M6 demo ("break the routine live")**, on the real project:
```powershell
uv run python -m nonna_cloud.seed --clear --today-until 10:30 --skip-room kitchen
uv run python -m nonna_cloud.checks --now 10:30 --report --telegram
```
The first line writes 14 normal days, plus a normal morning today with no kitchen. The second line says
"No kitchen sounds yet today. Maria is usually in the kitchen by 08:11", and posts it to Telegram.

You can rehearse it as often as you like: `--clear` also deletes **today's** routine alerts, so the live demo
still fires after a rehearsal. If the hub runs the checks (`serve --routine-checks`), restart it too, because it
remembers in memory what it already reported today.

## Telegram commands: /status, /ask, /help (extra)

The family can check on Maria from the group. Run this as a **third window** next to the hub, on the same laptop:
```powershell
cd cloud
uv run python -m nonna_cloud.bot
```
It reads `hub/.env` (bot token, chat id, HUB_TOKEN) and sets the `/` menu in Telegram itself.
- `/status`: is the hub on, which phones listen (and their battery), the last sound from Firestore.
- `/ask`: buttons with the rooms; tapping one makes that phone ask "Stai bene?" through the hub's `POST /ask`.
  `/ask kitchen` skips the buttons.
- Only the family group is answered, because `/ask` makes a phone speak in Maria's home.
- Only one program may read the bot's messages: stop the bot before running `telegram_setup chat-id`.
- For now Maria's answer to an `/ask` only shows in the hub's window; the hub sending it to the group is a
  small change on the hub's side.

## For teammates

- **Ebrahim (hub, E9):** run the checks every 15 minutes with `from nonna_cloud.checks import Checker`
  (example at the top of `checks.py`). Add `nonna-cloud = { path = "../cloud" }` to the hub's dependencies.
  `Checker.run()` returns findings; run the voice check for those with `voice_check=True`, then call
  `Checker.report()` and send the Telegram message. `report()` returns the alert it wrote, or `None` if that
  alert already existed. A missing home raises `MissingHome` (a normal `LookupError`), not `SystemExit`.
- **Ebrahim (hub, E6):** follow [docs/firestore-schema.md](../docs/firestore-schema.md). Events are D30: one
  `homes/{id}/events/{deviceId}_{startEpochMillis}_{category}` document per event (D38), with `room`, `deviceId`, `sound`,
  `confidence`, `start`, `end`, `source: "hub"`, and please also `category` (your category name; the routine
  learner uses it). Use Firestore `Timestamp`s (Python: timezone-aware `datetime`); the id makes offline-queue
  retries overwrite instead of duplicating. Write a `devices/{HUB_ID}` heartbeat (`kind: "hub"`) every 5 minutes; the
  cloud's hub-offline check reads every hub document (D39). Alert `type`s are your `rules.py` names.
- **A (Android):** the "my homes" query must be
  `whereArrayContains("memberEmails", user.email.lowercase())`, because without that filter the rules
  refuse the query. Alerts can only be moved forward (`sent → seen → resolved`), and `answeredBy` must be
  the signed-in email.
