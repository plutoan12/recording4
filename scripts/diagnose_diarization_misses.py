#!/usr/bin/env python3
"""Describe count-based missed speech by acoustic proxies, not causal labels.

Reference annotations are used only for offline diagnosis. This does not select
production retries or tune a model. Mixture RMS is not an individual voice's SNR.
"""

import argparse
import json
from pathlib import Path

import numpy as np
from prepare_conversation_evaluation import load_json
from run_sortformer_evaluation import sha256, write_private_json

from pipeline.speaker_disagreement import compare_turns


def diagnose(reference, prediction, audio, rate):
    duration = len(audio) / rate
    compare_turns(reference, prediction, duration)  # same strict timestamp validation
    # Acoustic strata must not change when a candidate changes turn boundaries.
    hop = max(1, round(rate * 0.02))
    levels = [
        20 * np.log10(max(float(np.sqrt(np.mean(audio[i : i + hop].astype(float) ** 2))), 1e-12))
        for i in range(0, len(audio), hop)
    ]
    times = sorted(
        {
            0.0,
            duration,
            *[i / rate for i in range(0, len(audio), hop)],
            *[t[k] for rows in (reference, prediction) for t in rows for k in ("start", "end")],
        }
    )
    groups = {}
    for start, end in zip(times, times[1:], strict=False):
        ref = [t for t in reference if t["start"] <= start < t["end"]]
        hyp = {t["speaker"] for t in prediction if t["start"] <= start < t["end"]}
        count = len({t["speaker"] for t in ref})
        if not count:
            continue
        missed = max(0, count - len(hyp)) * (end - start)
        total = count * (end - start)
        db = levels[min(len(levels) - 1, int(((start + end) / 2) * rate / hop))]
        bins = [
            "all",
            "overlap" if count > 1 else "single_speaker",
            "all_active_turns_le_0.5s"
            if all(t["end"] - t["start"] <= 0.5 for t in ref)
            else "includes_longer_turn",
            "mixture_below_minus40_dbfs"
            if db < -40
            else "mixture_minus40_to_minus30_dbfs"
            if db < -30
            else "mixture_at_least_minus30_dbfs",
        ]
        for name in bins:
            row = groups.setdefault(
                name, dict(reference_speaker_seconds=0.0, missed_speaker_seconds=0.0)
            )
            row["reference_speaker_seconds"] += total
            row["missed_speaker_seconds"] += missed
    for row in groups.values():
        row["miss_rate"] = row["missed_speaker_seconds"] / row["reference_speaker_seconds"]
    return dict(
        groups=groups,
        acoustic_frame_seconds=hop / rate,
        causal_conclusion=False,
        deploy_allowed=False,
    )


def main():
    import soundfile as sf

    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("audio", "reference", "prediction", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    prediction = load_json(args.prediction)
    if prediction["source_sha256"] != sha256(args.audio):
        raise ValueError("Different audio")
    audio, rate = sf.read(args.audio, dtype="float32")
    if audio.ndim != 1 or rate <= 0 or not len(audio) or not np.isfinite(audio).all():
        raise ValueError("Invalid mono audio")
    reference = load_json(args.reference)
    if isinstance(reference, dict):
        reference = reference["segments"]
    result = diagnose(reference, prediction["turns"], audio, rate)
    result["sha256"] = {
        name: sha256(getattr(args, name)) for name in ("audio", "reference", "prediction")
    }
    write_private_json(args.output, result)
    print(json.dumps(result["groups"]))


if __name__ == "__main__":
    main()
