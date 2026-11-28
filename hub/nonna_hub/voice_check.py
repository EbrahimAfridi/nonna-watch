"""The voice check: the phone asks "Are you okay?" and the hub listens for the answer.

Follows "Voice check, end to end" in docs/api-contract.md. The server decides what to do with the
answer (CONTEXT.md section 4); this module decides what counts as an answer.
"""

import asyncio
import re
from dataclasses import dataclass, field

from nonna_hub.help_words import find_phrases, words
from nonna_hub.protocol import now_ms
from nonna_hub.rules import Alert
from nonna_hub.speech import Utterance

ASK_PLAYED_TIMEOUT_S = 20  # contract: no ask_played within 20 s means the check failed
ANSWER_WINDOW_MS = 30_000  # contract: answers count for 30 s after the question ends
ANSWER_WAIT_S = 35  # those 30 s plus time for a late answer to get through Whisper
ECHO_MARGIN_MS = 300  # speech starting this soon after the question may still be the question

# Until E8 reads the home's settings: what the phone says when the family recorded no clip.
QUESTIONS = {
    "it": ("Stai bene?", "it-IT"),
    "en": ("Are you okay?", "en-US"),
    "hi": ("क्या आप ठीक हैं?", "hi-IN"),
    "ur": ("کیا آپ ٹھیک ہیں؟", "ur-PK"),
    "bs": ("Jesi li dobro?", "bs-BA"),
}

FINE_WORDS = {
    "it": ("sto bene", "tutto bene", "tutto a posto", "bene"),
    "en": ("fine", "okay", "ok", "all right", "alright", "all good"),
    "hi": ("ठीक", "ٹھیک", "theek", "thik"),
    "ur": ("ٹھیک", "ठीक", "theek", "thik"),
    "bs": ("dobro", "u redu", "okej", "ok"),
}

# "Non sto bene", "I'm not okay" and "ठीक नहीं" contain a fine word but mean the opposite. Any
# negation stops an answer from counting as fine, so a check errs towards alerting.
NEGATIONS = {"non", "no", "not", "nope", "ne", "nisam", "nije", "नहीं", "नही", "نہیں", "nahi", "nahin"}
# English "don't" and "isn't", found before words() splits them at the apostrophe. A lone "t" would
# also catch the Italian "t'ho detto" ("I told you"), which is not a negation.
CONTRACTED_NOT = re.compile(r"n['’]t\b")


def is_question(said: Utterance, sent_ms: int, ended_ms: int | None) -> bool:
    """Whether this speech may be the question itself, which can contain "bene" or "aiuto"."""
    return overlaps_question(said.start_ms, said.end_ms, sent_ms, ended_ms)


def overlaps_question(start_ms: int, end_ms: int, sent_ms: int, ended_ms: int | None) -> bool:
    """Whether a sound from start_ms to end_ms may be the phone playing the question.

    Until the phone reports when the question ended, anything that ends after it was sent counts.
    """
    if end_ms <= sent_ms:
        return False
    return ended_ms is None or start_ms < ended_ms + ECHO_MARGIN_MS


def answer(said: Utterance) -> tuple[str, str] | None:
    """("help", word) or ("fine", phrase) if this speech answers the check, otherwise None."""
    if said.help_words:
        return "help", said.help_words[0]
    for text in said.texts.values():
        if CONTRACTED_NOT.search(text.casefold()) or any(word in NEGATIONS for word in words(text)):
            return None
    for language, text in said.texts.items():
        fine = find_phrases(text, FINE_WORDS.get(language, ()))
        if fine:
            return "fine", fine[0]
    return None


def new_future() -> asyncio.Future:
    return asyncio.get_running_loop().create_future()


@dataclass
class VoiceCheck:
    """One check in one room. The phone and the speech fill the futures; the server awaits them."""

    ask_id: str
    reason: str  # an alert kind, a routine finding (routine_missing, long_silence) or "manual"
    alert: Alert | None = None  # the hub alert behind it, if any
    alert_sent: bool = False  # True when the alert went out at once and the check only adds a follow-up
    detected: tuple[int, int] | None = None  # (hub received, AI done) for an alert that waits for the check
    sent_ms: int = field(default_factory=now_ms)
    ended_ms: int | None = None  # when the phone finished playing the question, in phone time
    played: asyncio.Future = field(default_factory=new_future)
    answered: asyncio.Future = field(default_factory=new_future)
    done: asyncio.Future = field(default_factory=new_future)  # (outcome, detail) once the check is over

    def hear(self, said: Utterance) -> None:
        """Settle the check with the first speech after the question that says fine or help."""
        if self.answered.done() or self.ended_ms is None or said.start_ms > self.ended_ms + ANSWER_WINDOW_MS:
            return
        result = answer(said)
        if result:
            self.answered.set_result(result)
