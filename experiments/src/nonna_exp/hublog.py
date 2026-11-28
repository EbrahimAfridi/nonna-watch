"""Pull each alert's timing out of what the hub prints (Experiment 1 and 6).

The hub (`nonna-hub serve`) prints two lines per alert, both timed from the moment the sound was
CAPTURED on the phone:

    bathroom     14:03:12.5   ALERT        help_word aiuto   received +0.3 s, detected +1.8 s
    bathroom     14:03:12.5   SENT         +2.1 s after the sound

so for every alert we get three hops:
    received_s   sound captured on the phone -> audio arrived at the hub  (Wi-Fi, or internet for Cloud Run)
    detected_s   ... -> the hub's AI decided it is an alert                (YAMNet / VAD / Whisper)
    sent_s       ... -> Telegram accepted the message                     (internet)

The phone and the laptop must have synced clocks (NTP), because "captured" comes from the phone's clock.
The last hop, Telegram delivering to the family's phone, is not in the log; see experiments/README.md.

Save the hub's output to a file while it runs with:  uv run python -m nonna_exp.record_hub
(it starts the hub and writes experiments/hub.log in UTF-8; see record_hub.py).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

ALERT = re.compile(
    r"^(?P<room>\S+)\s+(?P<at>\d\d:\d\d:\d\d\.\d)\s+ALERT\s+(?P<what>.*?)"
    r"(?:\s+received \+(?P<received>[\d.]+) s, detected \+(?P<detected>[\d.]+) s)?\s*$"
)
SENT = re.compile(r"^(?P<room>\S+)\s+(?P<at>\d\d:\d\d:\d\d\.\d)\s+SENT\s+\+(?P<sent>[\d.]+) s after the sound")
NOT_SENT = re.compile(r"^(?P<room>\S+)\s+(?P<at>\d\d:\d\d:\d\d\.\d)\s+NOT SENT\s+(?P<error>.*)$")


@dataclass
class AlertTiming:
    room: str
    at: str                      # clock time of the sound, as the hub prints it
    kind: str                    # help_word, scream, thud, ...
    detail: str = ""
    received_s: float | None = None
    detected_s: float | None = None
    sent_s: float | None = None
    status: str = "pending"      # pending -> sent / not_sent
    error: str = ""
    extra: dict = field(default_factory=dict)

    def row(self) -> dict:
        return {"room": self.room, "at": self.at, "kind": self.kind, "detail": self.detail,
                "received_s": self.received_s, "detected_s": self.detected_s, "sent_s": self.sent_s,
                "status": self.status, "error": self.error}


class HubLogReader:
    """Feed it lines (all at once or as they come); it pairs each ALERT with its SENT / NOT SENT."""

    def __init__(self) -> None:
        self.alerts: list[AlertTiming] = []

    def feed(self, lines: Iterable[str]) -> list[AlertTiming]:
        """Returns the alerts that became complete (sent or not sent) with these lines."""
        done = []
        for line in lines:
            line = line.rstrip("\n")
            if m := ALERT.match(line):
                kind, _, detail = m["what"].partition(" ")
                self.alerts.append(AlertTiming(
                    room=m["room"], at=m["at"], kind=kind, detail=detail.strip(),
                    received_s=float(m["received"]) if m["received"] else None,
                    detected_s=float(m["detected"]) if m["detected"] else None))
            elif m := SENT.match(line):
                if a := self._pending(m["room"], m["at"]):
                    a.sent_s, a.status = float(m["sent"]), "sent"
                    done.append(a)
            elif m := NOT_SENT.match(line):
                if a := self._pending(m["room"], m["at"]):
                    a.status, a.error = "not_sent", m["error"]
                    done.append(a)
        return done

    def _pending(self, room: str, at: str) -> AlertTiming | None:
        for a in reversed(self.alerts):
            if a.room == room and a.at == at and a.status == "pending":
                return a
        return None


def parse(lines: Iterable[str]) -> list[AlertTiming]:
    reader = HubLogReader()
    reader.feed(lines)
    return reader.alerts
