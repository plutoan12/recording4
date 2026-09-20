"""Prepare target-ASR rows for prediction-only consensus speech gaps."""

import argparse
import math
from pathlib import Path

from prepare_conversation_evaluation import load_json
from run_sortformer_evaluation import sha256, write_private_json


def build_manifest(gaps, prediction, audio_path, duration=120, context=3):
    if not math.isfinite(duration) or duration <= 0 or not 0 <= context <= 10:
        raise ValueError("Invalid preparation policy")
    if not isinstance(audio_path, str) or not audio_path.startswith("/data/"):
        raise ValueError("Audio path must use the isolated data mount")
    for turn in prediction["turns"]:
        if (
            not isinstance(turn["speaker"], str)
            or not turn["speaker"]
            or not all(math.isfinite(x) for x in (turn["start"], turn["end"]))
            or not 0 <= turn["start"] < turn["end"] <= duration
        ):
            raise ValueError("Invalid prediction turn")
    labels = sorted({turn["speaker"] for turn in prediction["turns"]})
    if not labels:
        raise ValueError("No predicted speakers")
    rows = []
    seen = set()
    for gap in gaps["audit"]:
        gap_id = gap["id"]
        start, end = gap["start"], gap["end"]
        if (
            not isinstance(gap_id, str)
            or not gap_id
            or gap_id in seen
            or not all(math.isfinite(x) for x in (start, end))
            or not 0 <= start < end <= duration
        ):
            raise ValueError("Invalid or duplicate gap")
        seen.add(gap_id)
        for target in labels:
            rows.append(
                dict(
                    id=f"{gap_id}-{target}",
                    audio=audio_path,
                    language="en",
                    target=target,
                    turns=prediction["turns"],
                    start=max(0, start - context),
                    end=min(duration, end + context),
                    core_start=start,
                    core_end=end,
                    reference="",
                )
            )
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ["audio", "gaps", "prediction", "output"]:
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--container-audio", default="/data/en.wav")
    args = parser.parse_args()
    gaps = load_json(args.gaps)
    prediction = load_json(args.prediction)
    audio_sha = sha256(args.audio)
    if gaps["source_sha256"] != audio_sha or prediction["source_sha256"] != audio_sha:
        raise ValueError("Source audio changed")
    if gaps["selection_uses_reference"] or gaps["policy"] != {
        "word_guard_seconds": 0.1,
        "minimum_gap_seconds": 0.5,
        "context_seconds": 1,
    }:
        raise ValueError("Consensus gap policy changed")
    rows = build_manifest(gaps, prediction, args.container_audio)
    args.output.mkdir(mode=0o700, exist_ok=False)
    write_private_json(args.output / "manifest.json", rows)
    write_private_json(
        args.output / "baseline.json",
        [
            dict(
                id=row["id"],
                target=row["target"],
                hypothesis="",
                sha256=audio_sha,
                generation_possibly_truncated=False,
            )
            for row in rows
        ],
    )
    write_private_json(
        args.output / "protocol.json",
        dict(
            audio_sha256=audio_sha,
            gaps_sha256=sha256(args.gaps),
            prediction_sha256=sha256(args.prediction),
            manifest_sha256=sha256(args.output / "manifest.json"),
            baseline_sha256=sha256(args.output / "baseline.json"),
            gap_count=len(gaps["audit"]),
            target_count=len({row["target"] for row in rows}),
            decode_rows=len(rows),
            extra_context_seconds=3,
            reference_supplied_to_model=False,
            candidate_only=True,
            deployment_allowed=False,
        ),
    )
    print(dict(rows=len(rows), gaps=len(gaps["audit"])))


if __name__ == "__main__":
    main()
