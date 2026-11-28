"""Test-set naming rules (C6), so a script can tell from a file's name what it should trigger.

    <kind>_<detail>_<nn>.wav       16 kHz mono WAV is best; any length

    help_it_anna_03.wav     a help word in Italian (lang it/en/hi/ur/bs), speaker "anna", take 3
    thud_bag_07.wav         a heavy bag dropped                -> expect a "thud" sound event
    scream_maria_01.wav     a scream                           -> expect "scream"
    glass_esc50_12.wav      glass breaking                     -> expect "glass"
    smoke_alarm_01.wav      a smoke alarm                      -> expect "smoke_alarm"
    kitchen_tap_04.wav      everyday sound                     -> expect NO alert and NO help word
    tv_rai1_01.wav          TV or radio (tv_ / radio_)         -> expect NO alert; we count false alarms/hour
    speech_it_anna_02.wav   ordinary talk, no help word        -> expect NO help word
    esc50_<class>_<id>.wav  an ESC-50 clip, named by its ESC-50 class (glass_breaking -> glass, else negative)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

LANGUAGES = ("it", "en", "hi", "ur", "bs")
# The hub category each positive kind should produce (hub/nonna_hub/categories.py).
EXPECTED_CATEGORY = {"thud": "thud", "scream": "scream", "glass": "glass", "smoke": "smoke_alarm", "cry": "distress"}
NEGATIVE_KINDS = {"kitchen", "tv", "radio", "speech", "noise"}
ESC50_POSITIVE = {"glass_breaking": "glass", "crying_baby": "distress"}


@dataclass(frozen=True)
class Clip:
    path: Path
    kind: str                 # help / thud / scream / glass / smoke / cry / kitchen / tv / radio / speech / esc50
    lang: str | None          # only for help_ and speech_
    expect_help: bool         # a help word should be heard
    expect_category: str | None   # a safety category should be heard
    negative: bool            # nothing should fire (false-alarm material)

    @property
    def long_background(self) -> bool:
        return self.kind in {"tv", "radio"}


def parse(path: Path) -> Clip:
    parts = path.stem.lower().split("_")
    kind = parts[0]
    lang = parts[1] if kind in {"help", "speech"} and len(parts) > 1 and parts[1] in LANGUAGES else None
    if kind == "help":
        if lang is None:
            raise ValueError(f"{path.name}: help clips need a language, like help_it_anna_01.wav")
        return Clip(path, kind, lang, True, None, False)
    if kind in EXPECTED_CATEGORY:
        return Clip(path, kind, None, False, EXPECTED_CATEGORY[kind], False)
    if kind == "esc50":
        cls = "_".join(parts[1:-1])
        category = ESC50_POSITIVE.get(cls)
        return Clip(path, kind, None, False, category, category is None)
    if kind in NEGATIVE_KINDS:
        return Clip(path, kind, lang, False, None, True)
    raise ValueError(f"{path.name}: unknown kind '{kind}' (see the naming rules in testset.py)")
