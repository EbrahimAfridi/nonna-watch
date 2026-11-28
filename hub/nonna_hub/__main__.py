"""Command line: `uv run nonna-hub listen | serve | fake-phone`. See hub/README.md."""

import argparse
import os
import sys
from collections.abc import Iterable
from pathlib import Path

import numpy as np
import sounddevice

from nonna_hub import fake_phone, server
from nonna_hub.audio import SAMPLE_RATE, WindowSlicer, file_chunks, microphone_chunks
from nonna_hub.categories import Categorizer
from nonna_hub.cloud_sync import CloudSync, connect
from nonna_hub.events import Event, EventMerger
from nonna_hub.help_words import DEFAULT_HELP_WORDS, LANGUAGES
from nonna_hub.protocol import ROOMS
from nonna_hub.rules import Alert, RoomRules
from nonna_hub.sound import HOP_SAMPLES, SoundClassifier
from nonna_hub.speech import SpeechListener, Transcriber, Utterance
from nonna_hub.telegram import Telegram, TelegramError

LABELS_PER_LINE = 3
MIN_TOKEN_LENGTH = 16


def main() -> None:
    parser = argparse.ArgumentParser(prog="nonna-hub", description="Nonna Watch edge hub")
    commands = parser.add_subparsers(dest="command", required=True)
    languages_help = f"languages the home speaks, comma-separated, from {','.join(LANGUAGES)} (default: %(default)s)"

    listen = commands.add_parser("listen", help="print the household sounds and speech heard")
    listen.add_argument("--raw", action="store_true", help="print YAMNet's top labels every half second instead")
    listen.add_argument("--languages", type=language_list, default="it,en", help=languages_help)
    listen.add_argument("files", nargs="*", type=Path, help="audio files to label instead of the microphone")

    serve = commands.add_parser("serve", help="accept listener phones and label their audio")
    # Cloud Run tells the container which port to use through PORT.
    serve.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8000)), help="default: %(default)s")
    serve.add_argument("--languages", type=language_list, default="it,en", help=languages_help)
    serve.add_argument(
        "--routine-checks",
        action="store_true",
        help="run the routine and silence checks here every 15 minutes (billing Path B; needs Firestore)",
    )

    phone = commands.add_parser("fake-phone", help="stream audio files or the mic to a hub, like a phone")
    phone.add_argument("--room", required=True, choices=ROOMS)
    phone.add_argument("--hub", default="ws://localhost:8000/ws/listener", help="default: %(default)s")
    phone.add_argument("files", nargs="*", type=Path, help="audio files to stream instead of the microphone")

    commands.add_parser("telegram-test", help="send a test message to the family's Telegram group")

    args = parser.parse_args()
    if args.command == "listen":
        listen_to(args.files, args.raw, args.languages)
    elif args.command == "serve":
        hub_id, sync = os.environ.get("HUB_ID", "hub"), cloud_sync_from_env()
        if args.routine_checks and not sync:
            sys.exit("--routine-checks needs Firestore: set HOME_ID and GOOGLE_APPLICATION_CREDENTIALS (hub/README.md).")
        server.serve(hub_token(), hub_id, args.port, args.languages, telegram_from_env(), sync, args.routine_checks)
    elif args.command == "fake-phone":
        fake_phone.run(args.hub, hub_token(), args.room, args.files)
    else:
        telegram_test()


def language_list(text: str) -> list[str]:
    languages = [code.strip() for code in text.split(",") if code.strip()]
    if not languages or any(code not in LANGUAGES for code in languages):
        raise argparse.ArgumentTypeError(f"use codes from {', '.join(LANGUAGES)}, such as it,en")
    return languages


def listen_to(files: list[Path], raw: bool, languages: list[str]) -> None:
    classifier = SoundClassifier()
    speech = None if raw else SpeechListener(Transcriber(), languages, DEFAULT_HELP_WORDS)

    def show(chunks: Iterable[np.ndarray]) -> None:
        if speech is None:
            print_labels(classifier, chunks)
        else:
            print_events(classifier, speech, chunks)

    if files:
        for path in files:
            print(f"\n{path.name}")
            show(file_chunks(path))
    else:
        print(f"Listening on {sounddevice.query_devices(kind='input')['name']}. Ctrl+C to stop.")
        try:
            show(microphone_chunks())
        except KeyboardInterrupt:
            pass


def print_events(classifier: SoundClassifier, speech: SpeechListener, chunks: Iterable[np.ndarray]) -> None:
    """Events, speech and alerts, as the hub would see them. Alerts are only printed, never sent."""
    slicer = WindowSlicer(window=classifier.window_samples, hop=HOP_SAMPLES)
    categorizer = Categorizer(classifier.labels)
    merger = EventMerger(classifier.window_ms)
    rules = RoomRules()
    try:
        for second, chunk in enumerate(chunks):
            for start, window in slicer.push(chunk):
                window_ms = start * 1000 // SAMPLE_RATE
                detections = categorizer.detect(classifier.scores(window))
                for event in merger.push(window_ms, detections):
                    print_event(event)
                for alert in rules.on_window(window_ms, detections):
                    print_alert(alert)
            for said in speech.push(chunk, second * 1000):
                print_utterance(said)
                for alert in rules.on_speech(said):
                    print_alert(alert)
    finally:
        for event in merger.close_all():
            print_event(event)
        for said in speech.flush():
            print_utterance(said)
            for alert in rules.on_speech(said):
                print_alert(alert)


def print_event(event: Event) -> None:
    print(f"{seconds(event.start_ms, event.end_ms)}   {event.summary()}")


def print_utterance(said: Utterance) -> None:
    texts = "   ".join(f"[{language}] {text}" for language, text in said.texts.items())
    print(f"{seconds(said.start_ms, said.end_ms)}   {'said':<12} {texts}")
    if said.help_words:
        print(f"{seconds(said.start_ms, said.end_ms)}   {'HELP':<12} {', '.join(said.help_words)}")


def print_alert(alert: Alert) -> None:
    print(f"{alert.at_ms / 1000:7.1f} s            {'ALERT':<12} {alert.kind} {alert.detail}".rstrip())


def seconds(start_ms: int, end_ms: int) -> str:
    return f"{start_ms / 1000:7.1f} to {end_ms / 1000:5.1f} s"


def print_labels(classifier: SoundClassifier, chunks: Iterable[np.ndarray]) -> None:
    slicer = WindowSlicer(window=classifier.window_samples, hop=HOP_SAMPLES)
    for chunk in chunks:
        for start, window in slicer.push(chunk):
            top = classifier.top_labels(classifier.scores(window), LABELS_PER_LINE)
            labels = "   ".join(f"{label} {score:.2f}" for label, score in top)
            print(f"{start / SAMPLE_RATE:7.1f} s   {labels}")


def cloud_sync_from_env() -> CloudSync | None:
    key_path, home_id = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", ""), os.environ.get("HOME_ID", "")
    if not (key_path and home_id):
        return None
    if not Path(key_path).is_file():
        sys.exit(f"GOOGLE_APPLICATION_CREDENTIALS points to {key_path}, which does not exist.")
    return CloudSync(connect(key_path), home_id)


def telegram_from_env() -> Telegram | None:
    token, chat_id = os.environ.get("TELEGRAM_BOT_TOKEN", ""), os.environ.get("TELEGRAM_CHAT_ID", "")
    return Telegram(token, chat_id) if token and chat_id else None


def telegram_test() -> None:
    token, chat_id = os.environ.get("TELEGRAM_BOT_TOKEN", ""), os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token:
        sys.exit("Set TELEGRAM_BOT_TOKEN in hub/.env first (hub/README.md, Telegram alerts).")
    telegram = Telegram(token, chat_id)
    try:
        if chat_id:
            telegram.send("Nonna Watch: test message. Alerts from the hub will appear here.")
            print("Sent. It should be in the Telegram group now.")
            return
        chats = telegram.recent_chats()
    except (OSError, TelegramError) as error:
        sys.exit(f"Telegram did not work: {error}")
    if not chats:
        sys.exit("The bot has not seen any chat yet. Add it to the family group, send /start there, try again.")
    print("TELEGRAM_CHAT_ID is not set. Chats the bot has seen (a group's id starts with -):")
    for seen_id, name in chats:
        print(f"  {seen_id}  {name}")


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
