"""Stand-ins for the slow or speech-only models, shared by the tests."""

import numpy as np

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
