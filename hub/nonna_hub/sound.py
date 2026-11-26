"""Sound labels from YAMNet (521 AudioSet classes): Google's yamnet.tflite run with LiteRT.

It is the same model file MediaPipe's audio classifier uses, so phone-only mode (A10) sees the
same labels as the hub.
"""

import hashlib
import sys
import urllib.request
import zipfile
from pathlib import Path

import numpy as np
from ai_edge_litert.interpreter import Interpreter

from nonna_hub.audio import SAMPLE_RATE

# A versioned URL plus a checksum, so the model cannot change or be swapped under us.
MODEL_URL = "https://storage.googleapis.com/mediapipe-models/audio_classifier/yamnet/float32/1/yamnet.tflite"
MODEL_SHA256 = "4d8b4a53282dc83ef04e3e7dbc4fbc98082e34e44ed798e16c3a0cdd4c584faf"
MODEL_PATH = Path(__file__).resolve().parent.parent / "models" / "yamnet.tflite"

# Windows overlap by half, so a short bang (under ~0.47 s) always lands whole in one window.
HOP_SAMPLES = 8_000


class SoundClassifier:
    def __init__(self, model_path: Path = MODEL_PATH):
        if not model_path.exists():
            download_model(model_path)
        self.labels = read_labels(model_path)
        self._interpreter = Interpreter(model_path=str(model_path))
        self._interpreter.allocate_tensors()
        self._input = self._interpreter.get_input_details()[0]
        self._output = self._interpreter.get_output_details()[0]
        self.window_samples = int(self._input["shape"][-1])  # 15,600 = 0.975 s at 16 kHz
        self.window_ms = self.window_samples * 1000 // SAMPLE_RATE

    def scores(self, window: np.ndarray) -> np.ndarray:
        """One score per label for a window of 16 kHz mono audio in [-1, 1]."""
        samples = window.astype(np.float32, copy=False).reshape(self._input["shape"])
        self._interpreter.set_tensor(self._input["index"], samples)
        self._interpreter.invoke()
        return self._interpreter.get_tensor(self._output["index"]).reshape(-1)

    def top_labels(self, scores: np.ndarray, count: int) -> list[tuple[str, float]]:
        best = np.argsort(scores)[::-1][:count]
        return [(self.labels[i], float(scores[i])) for i in best]


def read_labels(model_path: Path) -> list[str]:
    # The label list is stored inside the .tflite file as a zip archive.
    with zipfile.ZipFile(model_path) as archive:
        return archive.read("yamnet_label_list.txt").decode().splitlines()


def download_model(path: Path) -> None:
    print(f"Downloading {MODEL_URL}", file=sys.stderr)
    with urllib.request.urlopen(MODEL_URL, timeout=60) as response:
        model = response.read()
    if hashlib.sha256(model).hexdigest() != MODEL_SHA256:
        raise RuntimeError(f"{MODEL_URL} does not match the expected SHA-256; not using it")
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(".part")
    partial.write_bytes(model)
    partial.replace(path)
