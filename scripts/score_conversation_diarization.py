#!/usr/bin/env python3
"""Score fixed-interval, overlap-inclusive DER from saved predictions; never infer."""

import argparse
import json
import sys
import wave
from importlib.metadata import version
from pathlib import Path

from compare_conversation_evaluation import fingerprint
from prepare_conversation_evaluation import load_json, number, prepare, private_file

COMPONENTS = ("total", "missed detection", "false alarm", "confusion")


def score_segments(reference, hypothesis, start, end):
    from pyannote.core import Annotation, Segment, Timeline
    from pyannote.metrics.diarization import DiarizationErrorRate

    if not number(start) or not number(end) or not 0 <= start < end:
        raise ValueError("Invalid evaluation interval")

    def annotation(turns):
        if not isinstance(turns, list):
            raise ValueError("Turns must be a list")
        result = Annotation()
        for index, turn in enumerate(turns):
            a, b, label = (turn[k] for k in ("start", "end", "speaker"))
            if not number(a) or not number(b) or not start <= a < b <= end:
                raise ValueError("Turn outside fixed evaluation interval")
            if not isinstance(label, str) or not label.strip():
                raise ValueError("Missing speaker label")
            result[Segment(a, b), index] = label
        # Repeated tracks of one speaker must not inflate speaker-time.
        return result.support()

    truth, prediction = annotation(reference), annotation(hypothesis)
    metric = DiarizationErrorRate(collar=0.0, skip_overlap=False)
    details = metric(truth, prediction, uem=Timeline([Segment(start, end)]), detailed=True)
    if details["total"] <= 0:
        raise ValueError("Reference has no scored speech")
    return {key: float(details[key]) for key in (*COMPONENTS, "diarization error rate")}


def score(manifest, root, lock, predictions):
    if prepare(manifest, root) != lock or not lock["ready_for_multilingual_evaluation"]:
        raise ValueError("Current inputs differ from complete cohort lock")
    if type(predictions.get("schema")) is not int or predictions["schema"] != 1:
        raise ValueError("Invalid prediction schema")
    if predictions.get("cohort_sha256") != fingerprint(lock):
        raise ValueError("Prediction cohort differs")
    if (
        not isinstance(predictions.get("model_revision"), str)
        or not predictions["model_revision"].strip()
    ):
        raise ValueError("Missing model revision")
    given = predictions["cases"]
    indexed = {row["id"]: row for row in given}
    expected = {row["id"]: row for row in lock["cases"]}
    if len(indexed) != len(given) or indexed.keys() != expected.keys():
        raise ValueError("Duplicate, missing or extra prediction cases")
    references = {row["id"]: row["reference"] for row in manifest["cases"]}
    rows = []
    for name, case in expected.items():
        row = indexed[name]
        if row.get("audio_sha256") != case["audio_sha256"]:
            raise ValueError("Prediction audio differs")
        status = row["status"]
        if status not in ("succeeded", "failed", "rejected"):
            raise ValueError("Invalid prediction status")
        if status != "succeeded" and row["turns"] != []:
            raise ValueError("Failed predictions must be empty, not partial success")
        reference = load_json(private_file(root, references[name]))["segments"]
        details = score_segments(
            reference, row["turns"], case["evaluation_start"], case["evaluation_end"]
        )
        rows.append(dict(id=name, language=case["language"], status=status, **details))

    def aggregate(group):
        totals = {key: sum(row[key] for row in group) for key in COMPONENTS}
        totals["diarization error rate"] = (
            sum(totals[key] for key in COMPONENTS[1:]) / totals["total"]
        )
        totals["failed_cases"] = sum(row["status"] != "succeeded" for row in group)
        return totals

    return dict(
        schema=1,
        metric="DER",
        cohort_sha256=fingerprint(lock),
        predictions_sha256=fingerprint(predictions),
        metric_version=version("pyannote.metrics"),
        core_version=version("pyannote.core"),
        collar=0,
        include_overlap=True,
        uem="fixed_manifest_interval",
        deploy_allowed=False,
        cases=rows,
        total=aggregate(rows),
        languages={
            lang: aggregate([r for r in rows if r["language"] == lang])
            for lang in sorted({r["language"] for r in rows})
        },
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("manifest", "root", "lock", "predictions", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    result = score(
        load_json(args.manifest), args.root, load_json(args.lock), load_json(args.predictions)
    )
    if args.output.exists():
        if load_json(args.output) != result:
            raise ValueError("Different existing output; use a new path")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"total": result["total"], "deploy_allowed": False}))
    raise SystemExit(2 if result["total"]["failed_cases"] else 0)


if __name__ == "__main__":
    try:
        main()
    except (
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        OSError,
        wave.Error,
        EOFError,
        ImportError,
    ):
        print("Invalid DER inputs/output or missing evaluation dependencies.", file=sys.stderr)
        raise SystemExit(1) from None
