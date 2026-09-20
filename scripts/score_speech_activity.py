#!/usr/bin/env python3
"""Score speech presence only from a complete, audio-bound human reference."""

import argparse
import json
import math
import sys
import wave
from pathlib import Path

from prepare_conversation_evaluation import load_json
from run_sortformer_evaluation import sha256


def merged_intervals(intervals, start, end):
    """Validate and merge intervals without clipping invalid evidence."""
    if not all(math.isfinite(value) for value in (start, end)) or not 0 <= start < end:
        raise ValueError("Invalid evaluation interval")
    validated = []
    for interval in intervals:
        if not isinstance(interval, list | tuple) or len(interval) != 2:
            raise ValueError("Invalid interval")
        a, b = interval
        if (
            isinstance(a, bool)
            or isinstance(b, bool)
            or not isinstance(a, int | float)
            or not isinstance(b, int | float)
            or not all(math.isfinite(value) for value in (a, b))
            or not start <= a < b <= end
        ):
            raise ValueError("Interval outside fixed evaluation range")
        validated.append([float(a), float(b)])
    result = []
    for a, b in sorted(validated):
        if result and a <= result[-1][1]:
            result[-1][1] = max(result[-1][1], b)
        else:
            result.append([a, b])
    return result


def _duration(intervals):
    return sum(end - start for start, end in intervals)


def _intersection(left, right):
    return sum(max(0, min(b, d) - max(a, c)) for a, b in left for c, d in right)


def score_activity(reference, prediction, start, end):
    truth = merged_intervals(reference, start, end)
    hypothesis = merged_intervals(prediction, start, end)
    reference_seconds = _duration(truth)
    if reference_seconds <= 0:
        raise ValueError("Reference has no speech")
    prediction_seconds = _duration(hypothesis)
    matched = _intersection(truth, hypothesis)
    missed = reference_seconds - matched
    false_alarm = prediction_seconds - matched
    return dict(
        reference_speech_seconds=reference_seconds,
        predicted_speech_seconds=prediction_seconds,
        matched_speech_seconds=matched,
        miss_seconds=missed,
        false_alarm_seconds=false_alarm,
        speech_error_seconds=missed + false_alarm,
        recall=matched / reference_seconds,
        precision=matched / prediction_seconds if prediction_seconds else 0.0,
    )


def score(audio, reference, prediction, evaluation_end, *, reference_sha256, prediction_sha256):
    with wave.open(str(audio), "rb") as source:
        if (source.getnchannels(), source.getframerate(), source.getsampwidth()) != (1, 16000, 2):
            raise ValueError("Expected mono 16 kHz PCM16 WAV")
        duration = source.getnframes() / source.getframerate()
    if not math.isfinite(evaluation_end) or not 0 < evaluation_end <= duration:
        raise ValueError("Invalid evaluation end")
    audio_sha = sha256(audio)
    if not isinstance(prediction, dict):
        raise ValueError("Invalid prediction")
    if type(prediction.get("schema")) is not int or prediction["schema"] != 1:
        raise ValueError("Invalid prediction schema")
    if prediction.get("source_sha256") != audio_sha:
        raise ValueError("Prediction differs from audio")
    revision = prediction.get("model_revision")
    if not isinstance(revision, str) or not revision.strip():
        raise ValueError("Missing model revision")
    if not isinstance(reference, dict):
        raise ValueError("Invalid reference")
    if type(reference.get("schema")) is not int or reference["schema"] != 1:
        raise ValueError("Invalid reference schema")
    if reference.get("source_sha256") != audio_sha:
        raise ValueError("Reference differs from audio")
    if reference.get("speech_presence_complete") is not True:
        raise ValueError("Reference does not cover all speech")
    annotated_interval = reference.get("annotated_interval")
    if (
        not isinstance(annotated_interval, list)
        or len(annotated_interval) != 2
        or any(isinstance(value, bool) for value in annotated_interval)
        or not all(isinstance(value, int | float) for value in annotated_interval)
        or not all(math.isfinite(value) for value in annotated_interval)
        or annotated_interval[0] != 0
        or annotated_interval[1] != evaluation_end
    ):
        raise ValueError("Reference does not cover evaluation interval")
    provenance = reference.get("provenance")
    if not isinstance(provenance, str) or not provenance.strip():
        raise ValueError("Missing reference provenance")
    turns = reference.get("turns")
    if not isinstance(turns, list) or not isinstance(prediction.get("timestamps"), list):
        raise ValueError("Invalid speech activity evidence")
    truth = []
    for turn in turns:
        if (
            not isinstance(turn, dict)
            or not isinstance(turn.get("speaker"), str)
            or not turn["speaker"].strip()
        ):
            raise ValueError("Invalid reference turn")
        truth.append([turn.get("start"), turn.get("end")])
    return dict(
        schema=2,
        metric="speech_presence",
        model_revision=revision,
        evaluation_start=0,
        evaluation_end=evaluation_end,
        audio_sha256=audio_sha,
        reference_sha256=reference_sha256,
        reference_speech_presence_complete=True,
        reference_annotated_interval=annotated_interval,
        reference_provenance=provenance.strip(),
        prediction_sha256=prediction_sha256,
        deploy_allowed=False,
        **score_activity(truth, prediction["timestamps"], 0, evaluation_end),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("audio", "reference", "prediction", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--evaluation-end", type=float, required=True)
    args = parser.parse_args()
    prediction = load_json(args.prediction)
    result = score(
        args.audio,
        load_json(args.reference),
        prediction,
        args.evaluation_end,
        reference_sha256=sha256(args.reference),
        prediction_sha256=sha256(args.prediction),
    )
    if args.output.exists():
        if load_json(args.output) != result:
            raise ValueError("Different existing output; use a new path")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2) + "\n")
    print(json.dumps({"speech_error_seconds": result["speech_error_seconds"]}))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, TypeError, OverflowError, OSError, wave.Error, EOFError):
        print("Invalid speech-activity inputs or output.", file=sys.stderr)
        raise SystemExit(1) from None
