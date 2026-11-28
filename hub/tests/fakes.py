"""Stand-ins for the slow or speech-only models, shared by the tests."""

import numpy as np
from google.api_core.exceptions import ServiceUnavailable

from nonna_hub.categories import Detection


def loud_parts(audio):
    """Stand-in for Silero VAD: every run of samples louder than 0.1 counts as speech."""
    loud = np.concatenate([[False], np.abs(audio) > 0.1, [False]])
    edges = np.flatnonzero(np.diff(loud.astype(int)))
    return [{"start": int(start), "end": int(end)} for start, end in zip(edges[::2], edges[1::2], strict=True)]


class FakeWhisper:
    def __init__(self, says):
        self.says = says
        self.calls = []

    def __call__(self, audio, language):
        self.calls.append((len(audio), language))
        return self.says.get(language, "")


class ScriptedWhisper:
    """Writes down the given lines in order, one per stretch of speech."""

    def __init__(self, *lines):
        self.lines = list(lines)

    def __call__(self, audio, language):
        return self.lines.pop(0) if self.lines else ""


class ThudInWindows:
    """Stand-in for the categorizer: a thud in the given windows, counted from 1, and nothing else."""

    def __init__(self, *thud_windows):
        self.thud_windows = set(thud_windows)
        self.windows = 0

    def detect(self, scores):
        self.windows += 1
        return [Detection("thud", 0.9, "Thump, thud")] if self.windows in self.thud_windows else []


class FakeFirestore:
    """Stand-in for firestore.Client: records every set() as (path, data, merge).

    The first `offline_writes` attempts fail as if the network were down.
    """

    def __init__(self, offline_writes=0):
        self.writes = []
        self.offline_writes = offline_writes

    def collection(self, name):
        return FakeReference(self, [name])


class FakeReference:
    def __init__(self, db, parts):
        self.db = db
        self.parts = parts

    def collection(self, name):
        return FakeReference(self.db, self.parts + [name])

    def document(self, name):
        return FakeReference(self.db, self.parts + [name])

    def set(self, data, merge=False, timeout=None):
        if self.db.offline_writes:
            self.db.offline_writes -= 1
            raise ServiceUnavailable("no network")
        self.db.writes.append(("/".join(self.parts), data, merge))


class FakeChecker:
    """Stand-in for nonna_cloud's Checker: finds the same findings on every run, like the real one
    until their alert is stored, and records what is reported."""

    def __init__(self, *findings, store_fails=False):
        self.findings = list(findings)
        self.store_fails = store_fails
        self.reported = []

    def run(self):
        return list(self.findings)

    def report(self, finding, voice_result=None):
        if self.store_fails:
            raise ConnectionError("Firestore unreachable")
        self.reported.append((finding.type, finding.room, voice_result))
        self.findings.remove(finding)


class HearsEverywhere:
    """Stand-in for the categorizer: one category in every window."""

    def __init__(self, category):
        self.category = category

    def detect(self, scores):
        return [Detection(self.category, 0.9, self.category)]
