import numpy as np
import pytest

from nonna_hub.audio import SAMPLE_RATE
from nonna_hub.sound import SoundClassifier


@pytest.fixture(scope="module")
def classifier():
    return SoundClassifier()


def top_label(classifier, window):
    return classifier.top_labels(classifier.scores(window), 1)[0][0]


def test_silence_is_labelled_silence(classifier):
    assert top_label(classifier, np.zeros(classifier.window_samples, dtype=np.float32)) == "Silence"


def test_pure_tone_is_labelled_sine_wave(classifier):
    seconds = np.arange(classifier.window_samples) / SAMPLE_RATE
    tone = 0.5 * np.sin(2 * np.pi * 440 * seconds)

    assert top_label(classifier, tone) == "Sine wave"
