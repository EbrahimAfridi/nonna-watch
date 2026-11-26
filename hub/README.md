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

## Test

```
uv run pytest
```
