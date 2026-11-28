"""Household sound categories: groups of YAMNet labels that mean one thing in a home.

The labels and thresholds were checked on 105 ESC-50 clips (35 classes). Tune them on our own phone
recordings. Generic labels that also fire on rain or normal breathing ("Water", "Gasp") are left out
on purpose, and speech and music need 0.6 because YAMNet gives them about 0.5 for many other sounds.
"""

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Category:
    name: str
    labels: tuple[str, ...]
    threshold: float = 0.3


@dataclass(frozen=True)
class Detection:
    category: str
    score: float
    label: str  # the YAMNet label that scored highest within the category


CATEGORIES = (
    # Safety. The alert rules (E5) start from these, and YAMNet scores thuds and glass weakly.
    Category("scream", ("Screaming", "Shout", "Yell")),
    Category("distress", ("Crying, sobbing", "Wail, moan", "Groan", "Whimper", "Wheeze")),
    Category("thud", ("Thump, thud", "Thunk", "Smash, crash"), threshold=0.2),
    Category("glass", ("Glass", "Shatter", "Breaking"), threshold=0.15),
    Category("smoke_alarm", ("Smoke detector, smoke alarm", "Fire alarm")),
    # Daily life, for the timeline and the routine checks.
    Category("speech", ("Speech", "Conversation", "Narration, monologue"), threshold=0.6),
    Category("cough", ("Cough", "Throat clearing", "Sneeze")),
    Category("snoring", ("Snoring",)),
    Category("footsteps", ("Walk, footsteps", "Shuffle")),
    Category(
        "door",
        ("Door", "Knock", "Slam", "Sliding door", "Cupboard open or close", "Drawer open or close"),
    ),
    Category("doorbell", ("Doorbell", "Ding-dong")),
    Category("phone", ("Telephone", "Telephone bell ringing", "Ringtone")),
    Category("alarm", ("Alarm", "Alarm clock", "Buzzer", "Beep, bleep")),
    Category(
        "water",
        (
            "Water tap, faucet",
            "Sink (filling or washing)",
            "Bathtub (filling or washing)",
            "Pour",
            "Fill (with liquid)",
        ),
    ),
    Category("toilet", ("Toilet flush",)),
    Category(
        "cooking",
        (
            "Dishes, pots, and pans",
            "Cutlery, silverware",
            "Frying (food)",
            "Chopping (food)",
            "Microwave oven",
            "Blender",
            "Boiling",
            "Sizzle",
        ),
    ),
    Category("cleaning", ("Vacuum cleaner",)),
    Category(
        "grooming",
        ("Toothbrush", "Electric toothbrush", "Hair dryer", "Electric shaver, electric razor"),
    ),
    Category("tv_music", ("Television", "Radio", "Music"), threshold=0.6),
)


class Categorizer:
    """Turns YAMNet's 521 scores into the household categories that pass their thresholds."""

    def __init__(self, labels: list[str]):
        position = {label: index for index, label in enumerate(labels)}
        # Looking every label up now makes a misspelt label fail at start-up instead of never matching.
        self._members = [(category, [position[label] for label in category.labels]) for category in CATEGORIES]
        self._labels = labels

    def detect(self, scores: np.ndarray) -> list[Detection]:
        detections = []
        for category, members in self._members:
            best = max(members, key=lambda index: scores[index])
            if scores[best] >= category.threshold:
                detections.append(Detection(category.name, float(scores[best]), self._labels[best]))
        return detections
