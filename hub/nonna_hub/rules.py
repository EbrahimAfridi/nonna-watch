"""Detection rules from CONTEXT.md section 4: which sounds and words alert the family."""

import time
from dataclasses import dataclass

from nonna_hub.categories import Detection
from nonna_hub.speech import Utterance

INSTANT = ("scream", "distress", "glass", "smoke_alarm")  # alert on the first window that hears them
# Sounds that show someone is up and about after a thud. A TV or a running tap does not count.
SIGNS_OF_LIFE = {"speech", "footsteps", "door", "cough", "cooking", "toilet", "grooming"}
THUD_SILENCE_MS = 10_000
COOLDOWN_MS = 60_000  # at most one alert of each kind per room per minute, however long the sound lasts

CHECK_FIRST = ("thud", "glass")  # ask "Are you okay?" first; alert only without a reassuring answer
CHECK_AFTER = ("help_word", "scream", "distress")  # alert at once, then ask; "fine" sends a follow-up

# Sounds that happen once rather than going on. After a reassuring answer the next one is a new
# incident and alerts again; screaming, crying or a smoke alarm can last minutes and stay limited
# to once a minute, or a TV scene would alert after every check.
ONE_OFF_KINDS = ("help_word", "thud", "glass")

CHECK_OUTCOMES = {
    "help": "Asked for help when checked.",
    "no_answer": "No answer to the check-in question.",
    "not_played": "The listener could not ask the check-in question.",
}

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
    check_outcome: str = ""  # a key of CHECK_OUTCOMES, for an alert raised after a voice check

    def message(self, room: str) -> str:
        text = MESSAGES[self.kind].format(detail=self.detail, room=room.replace("_", " "), time=local_time(self.at_ms))
        if self.check_outcome:
            text += " " + CHECK_OUTCOMES[self.check_outcome]
        return f"Nonna Watch: {text}"


def follow_up_message(alert: Alert, room: str, answer: str) -> str:
    """After an alert that went out at once: the reassuring answer to the voice check."""
    where = room.replace("_", " ")
    return (
        f"Nonna Watch: After the alert in the {where} at {local_time(alert.at_ms)}, "
        f'the answer to the check-in question was "{answer}".'
    )


def local_time(epoch_ms: int) -> str:
    return time.strftime("%H:%M:%S", time.localtime(epoch_ms / 1000))


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

    def reassured(self, kind: str) -> None:
        """The voice check started by an alert of this kind got a reassuring answer."""
        if kind in ONE_OFF_KINDS:
            self._last_alert_ms.pop(kind, None)

    def _alert(self, kind: str, at_ms: int, detail: str = "") -> list[Alert]:
        last_ms = self._last_alert_ms.get(kind)
        if last_ms is not None and at_ms - last_ms < COOLDOWN_MS:
            return []
        self._last_alert_ms[kind] = at_ms
        return [Alert(kind, at_ms, detail)]
