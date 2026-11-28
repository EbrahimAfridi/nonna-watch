"""Default settings and Maria's demo home (see docs/firestore-schema.md, `homes/{homeId}`)."""

from __future__ import annotations

DEFAULT_SETTINGS = {
    "minConfidence": 0.3,
    "thudSilenceSeconds": 10,
    "voiceCheckSeconds": 30,
    "longSilenceMinutes": 45,
    "offlineMinutes": 5,
    "heartbeatMinutes": 5,
    "waterRunningMinutes": 20,
    "routineMinDays": 7,
    "routineMinShare": 0.6,
    "routineGraceMinutes": 30,
}

# Help words per language: exactly decision D24 (the hub's hub/nonna_hub/help_words.py).
# Hindi and Urdu share one list with Devanagari, Urdu and Latin spellings, because Whisper may write
# either script for either language.
_HI_UR = ["बचाओ", "بچاؤ", "بچاو", "bachao", "मदद", "مدد", "madad", "madat"]
HELP_WORDS = {
    "it": ["aiuto", "aiutami", "aiutatemi", "soccorso"],
    "en": ["help"],
    "hi": _HI_UR,
    "ur": _HI_UR,
    "bs": ["upomoć", "upomoc", "pomoć", "pomoc", "pomozite", "pomagajte"],
}

# Answers to "Are you okay?" that mean: no alert. Exactly decision D27 (the hub's voice_check.py).
# The hub also treats any negation ("non sto bene") as NOT fine.
_HI_UR_FINE = ["ठीक", "ٹھیک", "theek", "thik"]
FINE_WORDS = {
    "it": ["sto bene", "tutto bene", "tutto a posto", "bene"],
    "en": ["fine", "okay", "ok", "all right", "alright", "all good"],
    "hi": _HI_UR_FINE,
    "ur": _HI_UR_FINE,
    "bs": ["dobro", "u redu", "okej", "ok"],
}

# Room ids are fixed by the listener protocol (decision D22).
ROOMS = ["kitchen", "bathroom", "bedroom", "living_room", "hallway"]


def demo_home(member_emails: list[str], telegram_chat_id: str = "") -> dict:
    """Maria, 84, lives alone in Rome (the example day in the requirements)."""
    return {
        "name": "Maria",
        "timezone": "Europe/Rome",
        "languages": ["it", "en"],
        "helpWords": HELP_WORDS,
        "fineWords": FINE_WORDS,
        "familyContacts": [
            {"name": "Luca", "phone": "+39 000 000 0000", "role": "son"},
            {"name": "Neighbour", "phone": "+39 000 000 0001", "role": "neighbour"},
        ],
        "memberEmails": sorted({e.strip().lower() for e in member_emails if e.strip()}),
        "telegramChatId": telegram_chat_id,
        "mode": "normal",
        "settings": dict(DEFAULT_SETTINGS),
    }
