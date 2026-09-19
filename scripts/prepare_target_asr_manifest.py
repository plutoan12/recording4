#!/usr/bin/env python3
"""Prepare independent per-language utterances; no reference text enters the model."""

import argparse
import json
import wave
from pathlib import Path


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    items = []
    for lang in ["ko", "en", "ja", "zh"]:
        directory = args.root / f"new-{lang}-speech"
        expected = json.loads((directory / "expected.json").read_text())["sentences"]
        for i, entry in enumerate(expected):
            path = directory / f"human{i}.wav"
            with wave.open(str(path), "rb") as audio:
                duration = audio.getnframes() / audio.getframerate()
            if duration > 30:
                raise ValueError("Sample exceeds short-form window")
            items.append(
                dict(
                    id=f"fleurs-{lang}-new-{i}",
                    audio=f"/data/new-{lang}-speech/human{i}.wav",
                    language=lang,
                    reference=entry["text"],
                    target="single",
                    turns=[dict(start=0, end=duration, speaker="single")],
                )
            )
    args.output.write_text(json.dumps(items, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
