import numpy as np
import pytest

from nonna_hub.categories import CATEGORIES, Categorizer, Detection
from nonna_hub.sound import SoundClassifier


@pytest.fixture(scope="module")
def labels():
    return SoundClassifier().labels


def scores_with(labels, named_scores):
    scores = np.zeros(len(labels), dtype=np.float32)
    for label, score in named_scores.items():
        scores[labels.index(label)] = score
    return scores


def test_every_category_label_is_a_yamnet_label(labels):
    misspelt = [label for category in CATEGORIES for label in category.labels if label not in labels]

    assert misspelt == []


def test_a_category_scores_its_best_label(labels):
    detections = Categorizer(labels).detect(scores_with(labels, {"Glass": 0.125, "Shatter": 0.25}))

    assert detections == [Detection("glass", 0.25, "Shatter")]


def test_silence_and_scores_below_a_threshold_are_dropped(labels):
    scores = scores_with(labels, {"Toilet flush": 0.75, "Speech": 0.375, "Silence": 0.75})

    assert [detection.category for detection in Categorizer(labels).detect(scores)] == ["toilet"]
