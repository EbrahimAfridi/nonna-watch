# The hub as a container, for Cloud Run (C8): the same code and models as on the laptop.
# Build from the repository root, because the hub uses the cloud package for the routine checks (E9).
# Cloud Run runs amd64:  docker build --platform linux/amd64 -f hub/Dockerfile -t nonna-hub .
FROM python:3.12-slim

# sounddevice loads PortAudio when it is imported, although a server never opens a microphone.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libportaudio2 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.12.18 /uv /usr/local/bin/uv
ENV UV_PYTHON_DOWNLOADS=never UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

# The hub finds the cloud package at ../cloud, as in the repository.
COPY cloud/pyproject.toml /app/cloud/
COPY cloud/src /app/cloud/src
WORKDIR /app/hub
# Dependencies first, so a code change does not reinstall them.
COPY hub/pyproject.toml hub/uv.lock hub/README.md ./
RUN uv sync --locked --no-dev --no-install-project

# YAMNet and Whisper go into the image, so a cold start never waits for a download. Only the files
# that say which models to fetch come first, so a change elsewhere in the code downloads nothing.
COPY hub/nonna_hub/__init__.py hub/nonna_hub/audio.py hub/nonna_hub/sound.py hub/nonna_hub/speech.py \
     hub/nonna_hub/help_words.py ./nonna_hub/
RUN .venv/bin/python -c "from nonna_hub.sound import SoundClassifier; from nonna_hub.speech import Transcriber; SoundClassifier(); Transcriber()"

COPY hub/nonna_hub ./nonna_hub
RUN uv sync --locked --no-dev

# HUB_TOKEN (and optionally TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, HUB_ID, HOME_ID,
# GOOGLE_APPLICATION_CREDENTIALS) come from Cloud Run's settings, never from the image.
# Cloud Run sets PORT.
ENV PATH="/app/hub/.venv/bin:$PATH" PYTHONUNBUFFERED=1 HF_HUB_OFFLINE=1 PORT=8080
EXPOSE 8080
CMD ["nonna-hub", "serve"]
