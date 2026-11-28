"""E6: the hub's writes to Firestore, as docs/firestore-schema.md describes (D30 to D32).

Each event becomes one document when it ends. Alerts are written at once and updated when their voice
check ends or Telegram confirms. Heartbeats for the hub and each listener follow every 5 minutes.

Writes wait in a queue for one background thread, so a slow or lost connection never holds up
listening. A write that fails for network reasons is retried until it gets through, in order; the
fixed document ids make a retry overwrite instead of duplicating.
"""

import itertools
import queue
import threading
import time
from datetime import UTC, datetime

from google.api_core import exceptions as google_errors
from google.auth.exceptions import TransportError
from google.cloud import firestore

from nonna_hub.events import Event
from nonna_hub.rules import Alert

RETRY_DELAYS_S = (1, 2, 5, 10, 30)  # then every 30 s until it works
NOTICES = ("water_running", "back_online")  # gentle notices rather than urgent alerts (schema)

# Worth retrying: the network or Firestore being unavailable for a while. Any other error means
# Firestore refused what was sent, which a retry would not change.
TEMPORARY = (
    google_errors.ServiceUnavailable,
    google_errors.DeadlineExceeded,
    google_errors.InternalServerError,
    google_errors.TooManyRequests,
    google_errors.RetryError,
    TransportError,
    OSError,
)


def connect(key_path: str) -> firestore.Client:
    return firestore.Client.from_service_account_json(key_path)


def listener_id(room: str) -> str:
    """One device document per room, as one listener per room (D23) and the seed data have it."""
    return f"listener-{room}"


def alert_id(room: str, alert: Alert) -> str:
    return f"{alert.kind}_{room}_{alert.at_ms}"


def timestamp(epoch_ms: int) -> datetime:
    return datetime.fromtimestamp(epoch_ms / 1000, tz=UTC)


class CloudSync:
    def __init__(self, db: firestore.Client, home_id: str):
        self.db = db
        self.home_id = home_id
        self._home = db.collection("homes").document(home_id)
        self._writes: queue.Queue = queue.Queue()
        threading.Thread(target=self._write_forever, daemon=True).start()

    def event(self, room: str, event: Event) -> None:
        device = listener_id(room)
        self._write(
            "events",
            # One window can start several events at once (speech over a TV): the category keeps them apart.
            f"{device}_{event.start_ms}_{event.category}",
            {
                "room": room,
                "deviceId": device,
                "sound": event.label,
                "category": event.category,
                "confidence": round(event.peak, 2),
                "start": timestamp(event.start_ms),
                "end": timestamp(event.end_ms),
                "source": "hub",
            },
        )

    def alert(self, room: str, alert: Alert, voice_check: str | None, timings: dict | None) -> None:
        document = {
            "type": alert.kind,
            "severity": "notice" if alert.kind in NOTICES else "alert",
            "room": room,
            "time": timestamp(alert.at_ms),
            "message": alert.message(room),
            "status": "sent",
            "answeredBy": None,
            "seenAt": None,
            "resolvedAt": None,
            "voiceCheck": {"asked": True, "result": voice_check} if voice_check else None,
            "followUp": None,
            "source": "hub",
        }
        if alert.detail:
            document["detail"] = {"word": alert.detail}
        if timings:
            document["timings"] = timings
        self._write("alerts", alert_id(room, alert), document)

    def update_alert(self, room: str, alert: Alert, fields: dict) -> None:
        self._write("alerts", alert_id(room, alert), fields, merge=True)

    def device(self, device_id: str, fields: dict) -> None:
        self._write("devices", device_id, fields, merge=True)

    def flush(self, timeout_s: float) -> None:
        """Wait for the queued writes, at most timeout_s: when the hub stops, and in tests."""
        deadline = time.monotonic() + timeout_s
        while self._writes.unfinished_tasks and time.monotonic() < deadline:
            time.sleep(0.05)

    def _write(self, collection: str, document_id: str, data: dict, merge: bool = False) -> None:
        self._writes.put((collection, document_id, data, merge))

    def _write_forever(self) -> None:
        while True:
            collection, document_id, data, merge = self._writes.get()
            for delay_s in itertools.chain(RETRY_DELAYS_S, itertools.repeat(RETRY_DELAYS_S[-1])):
                try:
                    self._home.collection(collection).document(document_id).set(data, merge=merge, timeout=10)
                    break
                except TEMPORARY as error:
                    print(f"Firestore unreachable ({type(error).__name__}); retrying in {delay_s} s")
                    time.sleep(delay_s)
                except Exception as error:  # refused, or a bug in what was sent: log it, keep the thread alive
                    print(f"Firestore write to {collection}/{document_id} dropped: {error}")
                    break
            self._writes.task_done()
