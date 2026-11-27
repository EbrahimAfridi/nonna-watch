# Hub

The edge part of Nonna Watch: a laptop in the house that labels room sounds with YAMNet and, in
later steps, receives audio from the listener phones and turns speech into help-word alerts.
Audio stays in memory and is never written to disk.

## Setup (once)

1. Install uv: https://docs.astral.sh/uv/getting-started/installation/
2. `cd hub` and `uv sync`. This installs Python 3.12 and the dependencies into `hub/.venv`.

The first run downloads Google's YAMNet model (4 MB) into `hub/models/` and checks its SHA-256.

## Run

```
uv run nonna-hub listen               # the laptop microphone (Ctrl+C to stop)
uv run nonna-hub listen a.wav b.mp3   # audio files instead
uv run nonna-hub listen --raw a.wav   # YAMNet's top three labels every half second
```

It prints one line per household event: when it started and ended, the category (water, toilet,
door, glass, ... see `nonna_hub/categories.py`), the peak score from 0 to 1, and the YAMNet label
behind it. An event ends after more than a second without its sound. `--raw` shows what YAMNet
hears before the categories, which helps when tuning them.

## Help words

`listen` and `serve` also write down speech with Whisper and look for help words. Whisper (`base`,
141 MB) downloads into `hub/models/whisper/` on first use, once; that took 9 minutes on our
connection. Whisper never guesses the language: it runs once per language the home speaks.

```
uv run nonna-hub listen --languages it,en,hi
uv run --env-file .env nonna-hub serve --languages it,en
```

Codes: `it` Italian, `en` English, `hi` Hindi, `ur` Urdu, `bs` Bosnian; the default is `it,en`.
Each language adds about half a second per phrase. The words are in `nonna_hub/help_words.py`
until the family app's settings arrive through Firestore. A help word is reported about 1 to 3 s
after the person stops speaking.

`listen` prints everything Whisper heard. `serve` prints only phrases with a help word, so the hub
keeps no running record of what is said at home.

If the microphone only ever shows `Silence`, give your terminal app microphone access:

- macOS: System Settings > Privacy & Security > Microphone
- Windows: Settings > Privacy & security > Microphone > Let desktop apps access your microphone

## Let phones connect

Once per laptop, create `hub/.env` with a random token. The file is gitignored; share the token
with teammates privately, never in git, a chat group or a URL. (The command refuses to overwrite an
existing `.env`.)

```
uv run python -c "import secrets; open('.env', 'x').write('HUB_TOKEN=' + secrets.token_urlsafe(24) + '\n')"
```

Start the hub:

```
uv run --env-file .env nonna-hub serve
```

It prints the address for the listener app, such as `ws://192.168.43.12:8000/ws/listener`, then
each phone's events with its room. If macOS or Windows asks whether to accept incoming
connections, allow it (Windows: private networks).

No phone yet? In a second terminal, a fake phone streams audio files or the laptop mic exactly as
the app will (docs/api-contract.md):

```
uv run --env-file .env nonna-hub fake-phone --room kitchen a.wav b.wav
uv run --env-file .env nonna-hub fake-phone --room bedroom
```

To try `/devices` and `/ask` from a browser, open http://localhost:8000/docs, click Authorize and
paste the token from `.env`.

## Alerts and Telegram

The rules in `nonna_hub/rules.py` raise an alert at once for a help word, screaming, crying or
moaning, glass breaking and a smoke alarm, and for a thud followed by 10 s without any sound of
movement. Each kind alerts at most once per room per minute. `serve` prints every alert with its
timing, which Experiment 1 uses:

```
kitchen      23:16:22.5   ALERT        help_word aiuto   received +0.6 s, detected +2.8 s
kitchen      23:16:22.5   SENT         +3.4 s after the sound
```

`serve` also sends alerts to the family's Telegram group. `listen` only prints them, so testing
with files never reaches the family. To set Telegram up once:

1. In Telegram, message @BotFather, send `/newbot` and follow the steps. It gives you a bot token.
2. Add the bot to the family group and send `/start` in the group.
3. Add `TELEGRAM_BOT_TOKEN=<the token>` to `hub/.env`. Share the token privately, never in git.
4. Run `uv run --env-file .env nonna-hub telegram-test`. It lists the chats the bot has seen; add
   the group's id (it starts with `-`) as `TELEGRAM_CHAT_ID=<id>` to `hub/.env`.
5. Run `telegram-test` again: a test message should appear in the group.

Without these two settings the hub still runs, and alerts only appear in its console.

Two notices need no sound: a room whose phone sends nothing, not even a heartbeat, for 5 minutes
is reported offline (and again when it is back), and a tap running for 20 minutes gets a gentle
note.

## Voice check

The phone asks "Are you okay?" (in the home's first language, so `Stai bene?` for `--languages
it,en`) and the hub listens for 30 s after the question ends:

- Thud or glass: the hub asks first and alerts only on a help word, no answer, or a phone that
  cannot play the question.
- Help word, screaming or crying: the alert goes out at once; if the answer is reassuring, a
  follow-up says so.

Fine words are in `nonna_hub/voice_check.py`. An answer with a negation ("non sto bene", "I'm not
okay") never counts as fine, so the check errs towards alerting. Everything heard while the question
plays is ignored, because the question itself says "bene".

To try it, connect a fake phone (it pretends to play the question for 2 s) and start a check from
http://localhost:8000/docs (`POST /ask`), then answer into the laptop mic.

## Test

```
uv run pytest
```

## Container for Cloud Run (E10)

`hub/Dockerfile` builds the same hub with YAMNet and Whisper inside, so a cold start downloads
nothing. Cloud Run runs amd64, so on a Mac with Apple Silicon add `--platform linux/amd64`:

```
cd hub
docker build --platform linux/amd64 -t nonna-hub .
docker run --rm -p 8080:8080 -e HUB_TOKEN=<token> nonna-hub
```

The image holds no secrets: pass `HUB_TOKEN` (and optionally `TELEGRAM_BOT_TOKEN`,
`TELEGRAM_CHAT_ID`, `HUB_ID`) as environment variables, on Cloud Run through Secret Manager.
Arguments after the image name replace the default command, for example
`nonna-hub serve --languages it,en,hi`.

Cloud Run settings that matter for the hub (C8):

- `--memory 1Gi --cpu 2`: the hub needs about 0.5 GB, and Whisper is faster with two CPUs.
- `--timeout 3600`: Cloud Run cuts a WebSocket after the request timeout (at most 60 min); the
  listener app reconnects, as the contract says.
- `--min-instances 0 --max-instances 3` (budget guardrails, section 11 of CONTEXT.md). The first
  phone after a quiet spell waits for a cold start; Experiment 1 times warm instances.
- Phones connect to `wss://<service-url>/ws/listener`.
