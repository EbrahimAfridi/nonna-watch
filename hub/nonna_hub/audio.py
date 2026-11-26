"""Where hub audio comes from, and how it is cut into windows for the models.

Every source yields 1-second chunks of 16 kHz mono float32 in [-1, 1], the same unit a listener
phone sends (docs/api-contract.md), so files and the laptop mic go through the same path as phones.
"""

import contextlib
import math
import queue
from collections.abc import Iterator
from pathlib import Path

import numpy as np
import sounddevice
from faster_whisper import decode_audio

SAMPLE_RATE = 16_000
CHUNK_SAMPLES = SAMPLE_RATE


def microphone_chunks() -> Iterator[np.ndarray]:
    """Yield 1-second chunks from the default microphone until interrupted.

    The sound card fills a queue from its own thread, so slow work such as Whisper delays the chunks
    instead of losing them.
    """
    recorded: queue.Queue[np.ndarray] = queue.Queue()

    def on_audio(block: np.ndarray, _frames: int, _time, _status) -> None:
        recorded.put(block[:, 0].copy())

    with sounddevice.InputStream(
        samplerate=SAMPLE_RATE, channels=1, dtype="float32", blocksize=CHUNK_SAMPLES, callback=on_audio
    ):
        while True:
            with contextlib.suppress(queue.Empty):  # waking every second lets Ctrl+C through on Windows
                yield recorded.get(timeout=1)


def file_chunks(path: Path) -> list[np.ndarray]:
    """Decode any audio file to 16 kHz mono and cut it into 1-second chunks."""
    return split_into_chunks(decode_audio(str(path), sampling_rate=SAMPLE_RATE))


def split_into_chunks(audio: np.ndarray) -> list[np.ndarray]:
    """Cut audio into 1-second chunks, padding the last one with silence."""
    chunk_count = math.ceil(len(audio) / CHUNK_SAMPLES)
    padded = np.zeros(chunk_count * CHUNK_SAMPLES, dtype=np.float32)
    padded[: len(audio)] = audio
    return list(padded.reshape(chunk_count, CHUNK_SAMPLES))


class WindowSlicer:
    """Turns a stream of chunks into overlapping fixed-size windows, wherever chunk edges fall."""

    def __init__(self, window: int, hop: int):
        self.window = window
        self.hop = hop
        self._pending = np.zeros(0, dtype=np.float32)
        self._pending_start = 0  # stream position, in samples, of _pending[0]

    @property
    def samples_pushed(self) -> int:
        return self._pending_start + len(self._pending)

    def push(self, chunk: np.ndarray) -> list[tuple[int, np.ndarray]]:
        """Add a chunk; return every window it completes as (start sample, samples)."""
        self._pending = np.concatenate([self._pending, chunk])
        windows = []
        while len(self._pending) >= self.window:
            windows.append((self._pending_start, self._pending[: self.window]))
            self._pending = self._pending[self.hop :]
            self._pending_start += self.hop
        return windows
