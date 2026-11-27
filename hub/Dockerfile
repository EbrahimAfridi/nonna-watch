# The hub as a container, for Cloud Run (C8): the same code and models as on the laptop.
# Cloud Run runs amd64, so build with:  docker build --platform linux/amd64 -t nonna-hub .
FROM python:3.12-slim

# sounddevice loads PortAudio when it is imported, although a server never opens a microphone.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libportaudio2 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.12.18 /uv /usr/local/bin/uv
ENV UV_PYTHON_DOWNLOADS=never UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

WORKDIR /app
# Dependencies first, so a code change does not reinstall them.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project
COPY nonna_hub ./nonna_hub
RUN uv sync --locked --no-dev

# YAMNet and Whisper go into the image, so a cold start never waits for a download.
RUN .venv/bin/python -c "from nonna_hub.sound import SoundClassifier; from nonna_hub.speech import Transcriber; SoundClassifier(); Transcriber()"

# HUB_TOKEN (and optionally TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID) come from Cloud Run's settings,
# never from the image. Cloud Run sets PORT.
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 HF_HUB_OFFLINE=1 PORT=8080
EXPOSE 8080
CMD ["nonna-hub", "serve"]
