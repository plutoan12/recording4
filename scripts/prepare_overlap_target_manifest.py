#!/usr/bin/env python3
"""Map anonymous predicted speaker IDs to evaluation references; never alter masks."""

import argparse
import itertools
import json
from pathlib import Path

import numpy as np
from measure_diarization_stress import sample


def main():
    import soundfile as sf

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--voices", type=Path, required=True)
    p.add_argument("--cache", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    pieces = []
    for name in ["mono-a0.wav", "mono-b0.wav", "mono-a1.wav", "mono-b1.wav"]:
        x, sr = sf.read(args.voices / name, dtype="float32")
        assert sr == 16000
        pieces.append(x * (0.08 / max(np.sqrt(np.mean(x * x)), 1e-8)))
    texts = [
        s["text"] for s in json.loads((args.voices / "expected.json").read_text())["sentences"]
    ]
    result = []
    for name, fraction in [("overlap_25pct", 0.25), ("overlap_50pct", 0.5)]:
        _, truth, active = sample(pieces, fraction)
        raw = json.loads((args.cache / (name + "-raw.json")).read_text())
        turns = raw["turns"]
        labels = sorted({t["speaker"] for t in turns})
        assert len(labels) == 2
        centers = (np.arange(active.shape[1]) + 0.5) * 0.02
        prediction = np.zeros((2, len(centers)), bool)
        for t in turns:
            prediction[labels.index(t["speaker"])] |= (centers >= t["start"]) & (centers < t["end"])
        order = max(
            itertools.permutations(range(2)),
            key=lambda perm: sum(
                np.logical_and(active[i], prediction[perm[i]]).sum() for i in range(2)
            ),
        )
        for i in range(2):
            result.append(
                dict(
                    id=name + "-" + str(i),
                    audio="/data/overlap/" + name + ".wav",
                    language="en",
                    target=labels[order[i]],
                    turns=turns,
                    reference=" ".join(texts[i::2]),
                )
            )
    args.output.write_text(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
