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
| `src/nonna_cloud/defaults.py` | Maria's home document: settings, help words in 5 languages. | C4 |
| `src/nonna_cloud/db.py` | Connects Python to the emulator or to the real Firestore. | |
| `src/nonna_cloud/telegram_setup.py` | Finds the family group's chat id and sends a test message. | C2 |
| `tests/test_seed.py` | Tests for the fake-history generator. | C4 |
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
npm run test:rules   # starts a throwaway Firestore emulator, runs 42 rules tests, stops it
uv run pytest        # seed-generator tests, no emulator needed
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

1. **Create the project.** Go to https://console.firebase.google.com → *Create a project* → name it
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
   npx firebase deploy --only firestore:rules,firestore:indexes --project YOUR-PROJECT-ID
   ```
8. **Add the team.** *Project settings → Users and permissions → Add member*: Ebrahim and A as **Editor**.
9. **Check it end to end** with the real project:
   ```powershell
   uv run python -m nonna_cloud.seed --member your.email@gmail.com --telegram-chat-id CHAT_ID_FROM_C2
   ```
   Then look at *Firestore Database* in the console: `homes/maria` with about 400 events.
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

## For teammates

- **Ebrahim (hub):** follow [docs/firestore-schema.md](../docs/firestore-schema.md). In particular, use
  Firestore `Timestamp`s (Python: timezone-aware `datetime`), use the event id `{deviceId}_{startEpochMillis}`
  so offline-queue retries don't duplicate, put `source: "hub"` on events, and write a `devices/hub` heartbeat.
- **A (Android):** the "my homes" query must be
  `whereArrayContains("memberEmails", user.email.lowercase())`, because without that filter the rules
  refuse the query. Alerts can only be moved forward (`sent → seen → resolved`), and `answeredBy` must be
  the signed-in email.
