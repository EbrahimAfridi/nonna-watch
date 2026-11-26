"""Stand-ins for the slow or speech-only models, shared by the tests."""

import numpy as np


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
