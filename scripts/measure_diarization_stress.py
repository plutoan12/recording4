#!/usr/bin/env python3
"""Measure controlled noise/overlap on four isolated LibriSpeech utterances.

Input mono-a0.wav, mono-b0.wav, mono-a1.wav, mono-b1.wav must be 16 kHz,
mono, with a/b denoting known speakers. No count hint is given to inference.
Energy-derived activity is a proxy reference, not manually annotated DER.
Output audio and raw metrics must remain outside version control.
"""

import argparse
import hashlib
import itertools
import json
import os
import sys
from pathlib import Path

import numpy as np

from pipeline.editing import Cue
from pipeline.speakers import assign_speakers
from worker.analysis import diarize

sr = 16000
speakers = ["A", "B", "A", "B"]


def sample(pieces, overlap):
    starts = []
    pos = sr
    for i, x in enumerate(pieces):
        if i:
            pos = (
                starts[-1] + len(pieces[i - 1]) + sr
                if not overlap
                else starts[-1]
                + len(pieces[i - 1])
                - int(min(len(pieces[i - 1]), len(x)) * overlap)
            )
        starts.append(pos)
    size = max(s + len(x) for s, x in zip(starts, pieces, strict=False)) + sr
    stems = np.zeros((2, size), dtype=np.float32)
    truth = []
    for s, x, lab in zip(starts, pieces, speakers, strict=False):
        stems[0 if lab == "A" else 1, s : s + len(x)] += x
        truth.append({"start": s / sr, "end": (s + len(x)) / sr, "text": lab, "speaker": lab})
    # Reference is energy activity from each isolated clean stem, not human annotation.
    hop = 320
    n = size // hop
    energy = np.sqrt(np.mean(stems[:, : n * hop].reshape(2, n, hop) ** 2, axis=2))
    active = energy > 0.008
    return stems.sum(axis=0), truth, active


def score(turns, truth, active):
    labs = sorted(set(t.speaker for t in turns))
    n = active.shape[1]
    pred = np.zeros((len(labs), n), bool)
    for t in turns:
        centers = (np.arange(n) + 0.5) * 0.02
        pred[labs.index(t.speaker)] |= (centers >= t.start) & (centers < t.end)
    refn = active.sum(0)
    pn = pred.sum(0)
    over = refn == 2
    union = refn > 0
    best = 0
    for perm in itertools.permutations(range(max(2, len(labs))), 2):
        best = max(
            best,
            sum(
                np.logical_and(active[i], pred[j]).sum() if j < len(labs) else 0
                for i, j in enumerate(perm)
            ),
        )
    labels = assign_speakers(
        [Cue(start=t["start"], end=t["end"], text=t["text"]) for t in truth], turns
    )
    hits = max(
        (
            sum(
                label is not None
                and dict(zip(["A", "B"], perm, strict=True)).get(t["speaker"]) == label
                for t, label in zip(truth, labels, strict=True)
            )
            for perm in itertools.permutations(labs + [None] * max(0, 2 - len(labs)), 2)
        ),
        default=0,
    )
    return {
        "detected_speakers": len(labs),
        "utterance_correct_of_4": hits,
        "energy_reference_speech_seconds": round(union.sum() * 0.02, 2),
        "energy_reference_overlap_seconds": round(over.sum() * 0.02, 2),
        "overlap_recall": float((pn[over] >= 2).mean()) if over.any() else None,
        "overlap_false_positive_seconds": round(np.logical_and(pn >= 2, ~over).sum() * 0.02, 2),
        "speaker_activity_recall_proxy": float(best / max(1, active.sum())),
    }


def main():
    import soundfile as sf

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not os.environ.get("R4_HF_TOKEN"):
        parser.error("R4_HF_TOKEN is required")
    root = args.directory
    out = args.output
    out.mkdir(parents=True, exist_ok=True)
    files = ["mono-a0.wav", "mono-b0.wav", "mono-a1.wav", "mono-b1.wav"]
    pieces = []
    for file in files:
        x, rate = sf.read(root / file, dtype="float32")
        if rate != sr or x.ndim != 1 or not len(x) or not np.isfinite(x).all():
            raise ValueError("Expected nonempty finite mono 16 kHz WAV")
        rms = np.sqrt(np.mean(x * x))
        pieces.append(x * (0.08 / max(rms, 1e-8)))
    original_hashes = {f: hashlib.sha256((root / f).read_bytes()).hexdigest() for f in files}

    cases = (
        [("clean", 0, None, 0)]
        + [(f"noise_{snr}db_seed{seed}", 0, snr, seed) for snr in [20, 10, 0] for seed in [17, 29]]
        + [
            (f"overlap_{int(ov*100)}pct" + ("_noise10db" if snr is not None else ""), ov, snr, 17)
            for ov in [0.25, 0.5]
            for snr in [None, 10]
        ]
    )
    results = []
    for name, ov, snr, seed in cases:
        x, truth, active = sample(pieces, ov)
        if snr is not None:
            rng = np.random.default_rng(seed)
            noise = rng.normal(size=len(x)).astype(np.float32)
            power = np.mean(x[: active.shape[1] * 320].reshape(-1, 320)[active.any(0)] ** 2)
            noise *= np.sqrt(power / (10 ** (snr / 10) * np.mean(noise**2)))
            x += noise
        peak = float(np.max(np.abs(x)))
        x *= min(1, 0.95 / max(peak, 1e-9))
        path = out / (name + ".wav")
        sf.write(path, x, sr, subtype="PCM_16")
        try:
            turns = diarize(path, token=os.environ["R4_HF_TOKEN"], device="cpu")
            r = {
                "case": name,
                "overlap_fraction_of_shorter_clip": ov,
                "snr_db": snr,
                "seed": seed,
                **score(turns, truth, active),
            }
        except Exception as e:
            r = {"case": name, "error_type": type(e).__name__}
        results.append(r)
        (out / "metrics.json").write_text(
            json.dumps(
                {
                    "reference": (
                        "20ms clean isolated-stem RMS > 0.008; " "not manual speech annotation"
                    ),
                    "speaker_count_hint": None,
                    "cases": results,
                },
                indent=2,
            )
        )
        print("RESULT " + json.dumps(r), flush=True)
    assert original_hashes == {
        f: hashlib.sha256((root / f).read_bytes()).hexdigest() for f in files
    }
    print("ORIGINALS_UNCHANGED", flush=True)
    return int(any("error_type" in result for result in results))


if __name__ == "__main__":
    sys.exit(main())
