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
uv run nonna-hub listen               # label the laptop microphone (Ctrl+C to stop)
uv run nonna-hub listen a.wav b.mp3   # label audio files instead
```

Every half second it prints the window's start time and YAMNet's top three labels with scores
from 0 to 1.

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
one line per phone every half second. If macOS or Windows asks whether to accept incoming
connections, allow it (Windows: private networks).

No phone yet? In a second terminal, a fake phone streams audio files or the laptop mic exactly as
the app will (docs/api-contract.md):

```
uv run --env-file .env nonna-hub fake-phone --room kitchen a.wav b.wav
uv run --env-file .env nonna-hub fake-phone --room bedroom
```

To try `/devices` and `/ask` from a browser, open http://localhost:8000/docs, click Authorize and
paste the token from `.env`.

## Test

```
uv run pytest
```
