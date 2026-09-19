#!/usr/bin/env python3
"""Whisper-small comparator using the same predicted target activity as DiCoW.

Overlap stays in the waveform; non-target-only and silent intervals are zeroed.
Reference transcripts are used only for evaluation after decoding.
"""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from verify_transcribe import distance, squeeze


def main():
    from faster_whisper import WhisperModel
    from faster_whisper.audio import decode_audio

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument(
        "--stems", type=Path, help="Use saved separator stems instead of activity masking"
    )
    args = p.parse_args()
    model = WhisperModel("small", device="cpu", compute_type="int8", cpu_threads=2)
    rows = []
    for item in json.loads(args.manifest.read_text()):
        path = Path(item["audio"])
        if args.stems:
            case = item["id"].rsplit("-", 1)[0]
            labels = sorted({t["speaker"] for t in item["turns"]})
            path = args.stems / (case + "-audit") / f"stem{labels.index(item['target'])}.wav"
            if not path.exists():
                continue  # Missing anchor prevented separation; not a successful sample.
        audio = decode_audio(str(path), sampling_rate=16000)
        active = np.zeros(len(audio), dtype=bool)
        for turn in item["turns"]:
            if turn["speaker"] == item["target"]:
                active[max(0, round(turn["start"] * 16000)) : round(turn["end"] * 16000)] = True
        if not args.stems:
            audio[~active] = 0
        segments, _ = model.transcribe(audio, language=item["language"], beam_size=5)
        text = " ".join(s.text for s in segments)
        ref, hyp = squeeze(item["reference"]).casefold(), squeeze(text).casefold()
        rows.append(
            dict(
                id=item["id"],
                method="separator_stem" if args.stems else "target_activity_mask",
                reference_characters=len(ref),
                errors=distance(ref, hyp),
                cer=distance(ref, hyp) / max(1, len(ref)),
                hypothesis=text,
                sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            )
        )
        args.output.write_text(json.dumps(rows, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
