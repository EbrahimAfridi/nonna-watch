"""Command line: `uv run nonna-hub listen [FILE ...]`."""

import argparse
from collections.abc import Iterable
from pathlib import Path

import numpy as np
import sounddevice

from nonna_hub.audio import SAMPLE_RATE, WindowSlicer, file_chunks, microphone_chunks
from nonna_hub.sound import HOP_SAMPLES, SoundClassifier

LABELS_PER_LINE = 3


def main() -> None:
    parser = argparse.ArgumentParser(prog="nonna-hub", description="Nonna Watch edge hub")
    commands = parser.add_subparsers(dest="command", required=True)
    listen = commands.add_parser("listen", help="print what YAMNet hears, every half second")
    listen.add_argument("files", nargs="*", type=Path, help="audio files to label instead of the microphone")
    args = parser.parse_args()

    classifier = SoundClassifier()
    if args.files:
        for path in args.files:
            print(f"\n{path.name}")
            print_labels(classifier, file_chunks(path))
    else:
        print(f"Listening on {sounddevice.query_devices(kind='input')['name']}. Ctrl+C to stop.")
        try:
            print_labels(classifier, microphone_chunks())
        except KeyboardInterrupt:
            pass


def print_labels(classifier: SoundClassifier, chunks: Iterable[np.ndarray]) -> None:
    slicer = WindowSlicer(window=classifier.window_samples, hop=HOP_SAMPLES)
    for chunk in chunks:
        for start, window in slicer.push(chunk):
            top = classifier.top_labels(classifier.scores(window), LABELS_PER_LINE)
            labels = "   ".join(f"{label} {score:.2f}" for label, score in top)
            print(f"{start / SAMPLE_RATE:7.1f} s   {labels}")


if __name__ == "__main__":
    main()
