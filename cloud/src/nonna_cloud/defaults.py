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

# Help words per language, with the spellings Whisper may produce (requirements, "Languages").
HELP_WORDS = {
    "it": ["aiuto", "aiutami", "aiutatemi"],
    "en": ["help", "help me"],
    "hi": ["bachao", "बचाओ", "madad", "मदद"],
    "ur": ["bachao", "بچاؤ", "बचाओ", "madad", "مدد"],
    "bs": ["upomoć", "upomoc", "pomoć", "pomoc"],
}

# Answers to "Are you okay?" that mean: no alert (voice check, E7).
FINE_WORDS = {
    "it": ["sto bene", "tutto bene", "tutto a posto"],
    "en": ["i'm fine", "i am fine", "i'm okay", "i am okay", "i'm ok"],
    "hi": ["main theek hoon", "मैं ठीक हूँ", "theek hoon"],
    "ur": ["main theek hoon", "میں ٹھیک ہوں", "theek hoon"],
    "bs": ["dobro sam", "u redu je", "sve je u redu"],
}

ROOMS = ["kitchen", "bathroom", "bedroom"]


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
