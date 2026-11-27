import numpy as np
from fakes import FakeWhisper, loud_parts

from nonna_hub.help_words import DEFAULT_HELP_WORDS
from nonna_hub.speech import SpeechListener

SECOND = 16_000


def listener_for(whisper, languages=("it",)):
    return SpeechListener(whisper, languages, DEFAULT_HELP_WORDS, find_speech=loud_parts)


def listen(listener, levels, start_ms=0):
    """Push one second of audio per level: 0.5 is a second of speech, 0 a second of silence."""
    heard = []
    for index, level in enumerate(levels):
        heard += listener.push(np.full(SECOND, level, dtype=np.float32), start_ms + 1000 * index)
    return heard


def test_speech_is_written_down_in_every_language_after_half_a_second_of_silence():
    whisper = FakeWhisper({"it": "Aiuto!", "en": "I wish you"})
    heard = listen(listener_for(whisper, ("it", "en")), [0, 0.5, 0.5, 0], start_ms=10_000)

    assert [(said.start_ms, said.end_ms, said.help_words) for said in heard] == [(11_000, 13_000, ["aiuto"])]
    assert whisper.calls == [(2 * SECOND, "it"), (2 * SECOND, "en")]


def test_silence_is_neither_kept_nor_written_down():
    whisper = FakeWhisper({"it": "pronto"})
    heard = listen(listener_for(whisper), [0] * 30 + [0.5, 0])

    assert [(said.start_ms, said.end_ms) for said in heard] == [(30_000, 31_000)]
    assert whisper.calls == [(SECOND, "it")]


def test_long_speech_is_written_down_in_ten_second_pieces():
    heard = listen(listener_for(FakeWhisper({})), [0.5] * 25)

    assert [(said.start_ms, said.end_ms) for said in heard] == [(0, 10_000), (10_000, 20_000)]


def test_flush_writes_down_speech_cut_off_by_the_end_of_the_stream():
    listener = listener_for(FakeWhisper({}))

    assert listen(listener, [0, 0.5]) == []
    assert [(said.start_ms, said.end_ms) for said in listener.flush()] == [(1_000, 2_000)]


def test_reset_forgets_speech_from_before_missing_frames():
    listener = listener_for(FakeWhisper({}))
    listen(listener, [0.5])
    listener.reset()

    heard = listen(listener, [0, 0.5, 0], start_ms=60_000)

    assert [(said.start_ms, said.end_ms) for said in heard] == [(61_000, 62_000)]
