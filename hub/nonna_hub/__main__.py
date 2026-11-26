"""Command line: `uv run nonna-hub listen | serve | fake-phone`. See hub/README.md."""

import argparse
import os
import sys
from collections.abc import Callable, Iterable
from pathlib import Path

import numpy as np
import sounddevice

from nonna_hub import fake_phone, server
from nonna_hub.audio import SAMPLE_RATE, WindowSlicer, file_chunks, microphone_chunks
from nonna_hub.categories import Categorizer
from nonna_hub.events import Event, EventMerger
from nonna_hub.protocol import ROOMS
from nonna_hub.sound import HOP_SAMPLES, SoundClassifier

LABELS_PER_LINE = 3
MIN_TOKEN_LENGTH = 16


def main() -> None:
    parser = argparse.ArgumentParser(prog="nonna-hub", description="Nonna Watch edge hub")
    commands = parser.add_subparsers(dest="command", required=True)

    listen = commands.add_parser("listen", help="print the household sounds heard, as events")
    listen.add_argument("--raw", action="store_true", help="print YAMNet's top labels every half second instead")
    listen.add_argument("files", nargs="*", type=Path, help="audio files to label instead of the microphone")

    serve = commands.add_parser("serve", help="accept listener phones and label their audio")
    serve.add_argument("--port", type=int, default=8000)

    phone = commands.add_parser("fake-phone", help="stream audio files or the mic to a hub, like a phone")
    phone.add_argument("--room", required=True, choices=ROOMS)
    phone.add_argument("--hub", default="ws://localhost:8000/ws/listener", help="default: %(default)s")
    phone.add_argument("files", nargs="*", type=Path, help="audio files to stream instead of the microphone")

    args = parser.parse_args()
    if args.command == "listen":
        listen_to(args.files, print_labels if args.raw else print_events)
    elif args.command == "serve":
        server.serve(hub_token(), os.environ.get("HUB_ID", "hub"), args.port)
    else:
        fake_phone.run(args.hub, hub_token(), args.room, args.files)


def listen_to(files: list[Path], print_sounds: Callable[[SoundClassifier, Iterable[np.ndarray]], None]) -> None:
    classifier = SoundClassifier()
    if files:
        for path in files:
            print(f"\n{path.name}")
            print_sounds(classifier, file_chunks(path))
    else:
        print(f"Listening on {sounddevice.query_devices(kind='input')['name']}. Ctrl+C to stop.")
        try:
            print_sounds(classifier, microphone_chunks())
        except KeyboardInterrupt:
            pass


def print_events(classifier: SoundClassifier, chunks: Iterable[np.ndarray]) -> None:
    slicer = WindowSlicer(window=classifier.window_samples, hop=HOP_SAMPLES)
    categorizer = Categorizer(classifier.labels)
    merger = EventMerger(classifier.window_ms)
    try:
        for chunk in chunks:
            for start, window in slicer.push(chunk):
                detections = categorizer.detect(classifier.scores(window))
                for event in merger.push(start * 1000 // SAMPLE_RATE, detections):
                    print_event(event)
    finally:
        for event in merger.close_all():
            print_event(event)


def print_event(event: Event) -> None:
    print(f"{event.start_ms / 1000:7.1f} to {event.end_ms / 1000:5.1f} s   {event.summary()}")


def print_labels(classifier: SoundClassifier, chunks: Iterable[np.ndarray]) -> None:
    slicer = WindowSlicer(window=classifier.window_samples, hop=HOP_SAMPLES)
    for chunk in chunks:
        for start, window in slicer.push(chunk):
            top = classifier.top_labels(classifier.scores(window), LABELS_PER_LINE)
            labels = "   ".join(f"{label} {score:.2f}" for label, score in top)
            print(f"{start / SAMPLE_RATE:7.1f} s   {labels}")


def hub_token() -> str:
    token = os.environ.get("HUB_TOKEN", "")
    if len(token) < MIN_TOKEN_LENGTH:
        sys.exit(
            f"HUB_TOKEN is missing or shorter than {MIN_TOKEN_LENGTH} characters. Create hub/.env as "
            "hub/README.md shows and run with `uv run --env-file .env ...`."
        )
    return token


if __name__ == "__main__":
    main()
