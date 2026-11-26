"""Detection rules from CONTEXT.md section 4: which sounds and words alert the family.

Thuds and glass are meant to trigger the voice check ("Are you okay?") first. Until that exists
(E7), they alert directly like the others.
"""

import time
from dataclasses import dataclass

from nonna_hub.categories import Detection
from nonna_hub.speech import Utterance

INSTANT = ("scream", "distress", "glass", "smoke_alarm")  # alert on the first window that hears them
# Sounds that show someone is up and about after a thud. A TV or a running tap does not count.
SIGNS_OF_LIFE = {"speech", "footsteps", "door", "cough", "cooking", "toilet", "grooming"}
THUD_SILENCE_MS = 10_000
COOLDOWN_MS = 60_000  # at most one alert of each kind per room per minute, however long the sound lasts

MESSAGES = {
    "help_word": 'Help word "{detail}" heard in the {room} at {time}.',
    "scream": "Screaming heard in the {room} at {time}.",
    "distress": "Crying or moaning heard in the {room} at {time}.",
    "thud": "A heavy thud in the {room} at {time}, then 10 s without movement: possible fall.",
    "glass": "Glass breaking in the {room} at {time}.",
    "smoke_alarm": "Smoke alarm sounding in the {room} at {time}.",
}


@dataclass(frozen=True)
class Alert:
    kind: str  # a key of MESSAGES
    at_ms: int  # when the sound was captured
    detail: str = ""  # the help words heard, for help_word

    def message(self, room: str) -> str:
        clock = time.strftime("%H:%M:%S", time.localtime(self.at_ms / 1000))
        text = MESSAGES[self.kind].format(detail=self.detail, room=room.replace("_", " "), time=clock)
        return f"Nonna Watch: {text}"


class RoomRules:
    """One room's rules: per-window detections and help words in, alerts out."""

    def __init__(self):
        self._last_alert_ms: dict[str, int] = {}
        self._thud_ms: int | None = None  # a thud still waiting to see whether anyone moves

    def on_window(self, window_ms: int, detections: list[Detection]) -> list[Alert]:
        heard = {detection.category for detection in detections}
        alerts = []
        for kind in INSTANT:
            if kind in heard:
                alerts += self._alert(kind, window_ms)
        if "thud" in heard:
            self._thud_ms = window_ms
        elif self._thud_ms is not None:
            if heard & SIGNS_OF_LIFE:
                self._thud_ms = None
            elif window_ms - self._thud_ms >= THUD_SILENCE_MS:
                alerts += self._alert("thud", self._thud_ms)
                self._thud_ms = None
        return alerts

    def on_speech(self, said: Utterance) -> list[Alert]:
        if not said.help_words:
            return []
        return self._alert("help_word", said.end_ms, ", ".join(said.help_words))

    def _alert(self, kind: str, at_ms: int, detail: str = "") -> list[Alert]:
        last_ms = self._last_alert_ms.get(kind)
        if last_ms is not None and at_ms - last_ms < COOLDOWN_MS:
            return []
        self._last_alert_ms[kind] = at_ms
        return [Alert(kind, at_ms, detail)]
