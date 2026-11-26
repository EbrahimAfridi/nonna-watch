"""Speech to help words: Silero VAD finds speech, faster-whisper writes it down, help_words checks it.

Whisper never guesses the language; it runs once per language the home speaks (D5). It only gets
finished stretches of speech, never fixed 1-second slices that would cut words in half (D6).
"""

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass

import numpy as np
from faster_whisper import WhisperModel
from faster_whisper.vad import VadOptions, get_speech_timestamps

from nonna_hub.audio import SAMPLE_RATE
from nonna_hub.help_words import find_phrases
from nonna_hub.sound import MODELS_DIR

WHISPER_MODEL = "base"
WHISPER_REVISION = "ebe41f70d5b6dfa9166e2c581c45c9c0cfc57b66"  # Systran/faster-whisper-base, pinned
VAD_OPTIONS = VadOptions(min_silence_duration_ms=500, speech_pad_ms=200)

END_OF_SPEECH_SAMPLES = SAMPLE_RATE // 2  # speech counts as finished after half a second of silence
MAX_SPEECH_SAMPLES = 10 * SAMPLE_RATE  # longer speech, such as a TV, is written down in 10 s pieces
QUIET_TAIL_SAMPLES = SAMPLE_RATE // 2  # kept while nobody speaks, so a word at a chunk edge stays whole

Segments = list[dict[str, int]]  # [{"start": sample, "end": sample}, ...] as Silero returns them


@dataclass
class Utterance:
    start_ms: int
    end_ms: int
    texts: dict[str, str]  # what Whisper wrote, by language
    help_words: list[str]  # help words found in any of the texts


class Transcriber:
    def __init__(self):
        self._model = WhisperModel(
            WHISPER_MODEL,
            device="cpu",
            compute_type="int8",
            download_root=str(MODELS_DIR / "whisper"),
            revision=WHISPER_REVISION,
        )

    def __call__(self, audio: np.ndarray, language: str) -> str:
        # Whisper's default retries unsure phrases at a higher temperature, which samples at random: one
        # Hindi clip came back three different ways. Temperature 0 gives the same words for the same
        # audio every time, and beam search keeps it accurate for about 0.05 s more.
        segments, _info = self._model.transcribe(
            audio,
            language=language,
            beam_size=5,
            temperature=0.0,
            condition_on_previous_text=False,
            without_timestamps=True,
        )
        return " ".join(segment.text.strip() for segment in segments)


def find_speech(audio: np.ndarray) -> Segments:
    return get_speech_timestamps(audio, VAD_OPTIONS)


class SpeechListener:
    """One room's speech: keeps the audio of speech still going, writes finished speech down."""

    def __init__(
        self,
        transcribe: Callable[[np.ndarray, str], str],
        languages: Iterable[str],
        help_words: Mapping[str, Iterable[str]],
        find_speech: Callable[[np.ndarray], Segments] = find_speech,
    ):
        self._transcribe = transcribe
        self._languages = list(languages)
        self._help_words = help_words
        self._find_speech = find_speech
        self._audio = np.zeros(0, dtype=np.float32)
        self._audio_start_ms = 0

    def push(self, chunk: np.ndarray, capture_ms: int) -> list[Utterance]:
        """Add a chunk of audio; return what was said if a stretch of speech has just finished."""
        if len(self._audio) == 0:
            self._audio_start_ms = capture_ms
        self._audio = np.concatenate([self._audio, chunk])

        segments = self._find_speech(self._audio)
        if not segments:
            self._keep_from(len(self._audio) - QUIET_TAIL_SAMPLES)
            return []
        finished = [segment for segment in segments if len(self._audio) - segment["end"] >= END_OF_SPEECH_SAMPLES]
        if finished:
            end = finished[-1]["end"]
        elif len(self._audio) >= MAX_SPEECH_SAMPLES:
            end = len(self._audio)
        else:
            self._keep_from(segments[0]["start"])
            return []
        utterance = self._write_down(segments[0]["start"], end)
        self._keep_from(end)
        return [utterance]

    def flush(self) -> list[Utterance]:
        """Write down any speech still in progress, for when the stream stops."""
        segments = self._find_speech(self._audio) if len(self._audio) else []
        utterances = [self._write_down(segments[0]["start"], segments[-1]["end"])] if segments else []
        self.reset()
        return utterances

    def reset(self) -> None:
        """Forget buffered audio, for when frames went missing and the audio is no longer continuous."""
        self._audio = np.zeros(0, dtype=np.float32)

    def _write_down(self, start: int, end: int) -> Utterance:
        speech = self._audio[start:end]
        texts = {language: self._transcribe(speech, language) for language in self._languages}
        found = [
            word for language, text in texts.items() for word in find_phrases(text, self._help_words[language])
        ]
        unique = list(dict.fromkeys(found))  # "bachao" can match in both Hindi and Urdu
        return Utterance(self._ms(start), self._ms(end), texts, unique)

    def _keep_from(self, sample: int) -> None:
        sample = max(0, sample)
        self._audio_start_ms = self._ms(sample)
        self._audio = self._audio[sample:]

    def _ms(self, sample: int) -> int:
        return self._audio_start_ms + sample * 1000 // SAMPLE_RATE
