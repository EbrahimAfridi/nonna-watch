"""Connect to Firestore: the local emulator, or the real Firebase project.

Emulator (no internet, no key, safe to break):
    start it with `npm run emulators` in cloud/, then pass emulator=True.

Real project:
    needs the service-account key (shared privately, never committed). Put it at
    cloud/secrets/service-account.json, or point GOOGLE_APPLICATION_CREDENTIALS at it.
"""

from __future__ import annotations

import os
from pathlib import Path

from google.cloud import firestore

EMULATOR_HOST = "127.0.0.1:8080"
EMULATOR_PROJECT = "demo-nonna-watch"   # "demo-" ids only ever talk to the emulator
DEFAULT_KEY = Path(__file__).resolve().parents[2] / "secrets" / "service-account.json"


def connect(emulator: bool = False, key: str | os.PathLike | None = None) -> firestore.Client:
    if emulator:
        # The client library sees this variable and talks to the emulator instead of Google.
        os.environ["FIRESTORE_EMULATOR_HOST"] = EMULATOR_HOST
        return firestore.Client(project=EMULATOR_PROJECT)

    os.environ.pop("FIRESTORE_EMULATOR_HOST", None)
    key_path = Path(key or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") or DEFAULT_KEY)
    if not key_path.exists():
        raise SystemExit(
            f"No service-account key at {key_path}.\n"
            "Use --emulator, or put the key there (see cloud/README.md, step C1)."
        )
    return firestore.Client.from_service_account_json(str(key_path))
