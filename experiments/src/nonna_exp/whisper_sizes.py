"""Experiment 4: which Whisper size is enough? tiny vs base vs small, per language.

    uv sync --extra whisper                       # once: installs faster-whisper (large download)
    uv run python -m nonna_exp.whisper_sizes data/help_*.wav --sizes tiny,base,small

For each size and each help_<lang>_... recording, it transcribes the clip the way the hub does (language
forced from the file name, beam search, temperature 0, D5/D26) and checks for a help word with the
hub's OWN matching code (hub/nonna_hub/help_words.py), so the numbers mean the same as in the hub.

Results: results/exp4_whisper_sizes.csv, one row per size and file: seconds to transcribe, and whether
a help word was found. Only the matched help words are saved, never the full transcript.
The first run of each size downloads it (tiny 75 MB, base 141 MB, small 460 MB).
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import time
from pathlib import Path

from nonna_exp import HUB, RESULTS
from nonna_exp.testset import parse

FIELDS = ["size", "file", "lang", "seconds", "caught", "matched"]


def hub_help_words():
    """Load hub/nonna_hub/help_words.py directly (it only uses the standard library)."""
    path = HUB / "nonna_hub" / "help_words.py"
    spec = importlib.util.spec_from_file_location("hub_help_words", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Experiment 4: Whisper sizes, speed vs help words caught (C7).")
    ap.add_argument("files", nargs="+", type=Path)
    ap.add_argument("--sizes", default="tiny,base,small")
    ap.add_argument("--out", type=Path, default=RESULTS / "exp4_whisper_sizes.csv")
    args = ap.parse_args(argv)

    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise SystemExit("faster-whisper is not installed. Run: uv sync --extra whisper")
    hw = hub_help_words()
    clips = [c for c in (parse(f) for f in args.files) if c.kind == "help"]
    if not clips:
        raise SystemExit("No help_<lang>_... files given.")

    rows = []
    for size in args.sizes.split(","):
        print(f"Whisper {size} ...")
        model = WhisperModel(size, device="cpu", compute_type="int8")
        for c in clips:
            t0 = time.perf_counter()
            # Exactly the hub's settings (hub/nonna_hub/speech.py, Transcriber).
            segments, _ = model.transcribe(str(c.path), language=c.lang, beam_size=5, temperature=0.0,
                                           condition_on_previous_text=False, without_timestamps=True)
            text = " ".join(s.text.strip() for s in segments)
            seconds = time.perf_counter() - t0
            matched = hw.find_phrases(text, hw.DEFAULT_HELP_WORDS[c.lang])
            rows.append({"size": size, "file": c.path.name, "lang": c.lang, "seconds": round(seconds, 3),
                         "caught": int(bool(matched)), "matched": "; ".join(matched)})
        caught = [r for r in rows if r["size"] == size]
        print(f"  caught {sum(r['caught'] for r in caught)}/{len(caught)}, "
              f"mean {sum(r['seconds'] for r in caught) / len(caught):.2f} s per clip")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"Saved to {args.out}")


if __name__ == "__main__":
    main()
