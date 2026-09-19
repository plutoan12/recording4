#!/usr/bin/env python3
"""Compare scored speaker assignments against a revalidated private cohort lock.

This consumes scores; it does not run models, judge transcripts, or authorize deployment.
"""

import argparse
import hashlib
import json
import sys
import wave
from pathlib import Path

from check_speaker_quality import COUNTS, evaluate, indexed
from prepare_conversation_evaluation import load_json, prepare


def fingerprint(lock):
    encoded = json.dumps(lock, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def compare(lock, baseline, candidate):
    if lock.get("ready_for_multilingual_evaluation") is not True:
        raise ValueError("Incomplete multilingual cohort")
    expected = {row["id"]: row for row in lock["cases"]}
    if len(expected) != len(lock["cases"]):
        raise ValueError("Duplicate locked case")
    checked = []
    failures = []
    for label, report in (("baseline", baseline), ("candidate", candidate)):
        if type(report.get("schema")) is not int or report["schema"] != 1:
            raise ValueError("Unsupported score schema")
        if report.get("cohort_sha256") != fingerprint(lock):
            raise ValueError("Report belongs to a different cohort")
        rows = indexed(report["cases"])
        if rows.keys() != expected.keys():
            raise ValueError("Missing or extra scored cases")
        for name, row in rows.items():
            source = expected[name]
            if (
                row["sha256"] != source["audio_sha256"]
                or row.get("reference_sha256") != source["reference_sha256"]
                or row["total_characters"] != source["reference_characters"]
                or row.get("language") != source["language"]
            ):
                raise ValueError("Score inputs or denominator differ from the locked cohort")
            if row.get("status") not in ("succeeded", "failed", "rejected"):
                raise ValueError("Score status is missing or unsupported")
            if row["status"] != "succeeded":
                if row["word_correct"] or row["word_wrong"]:
                    raise ValueError("Failed/rejected cases must retain all characters unresolved")
                failures.append(dict(report=label, case=name, status=row["status"]))
        checked.append(rows)
    result = evaluate(baseline["cases"], candidate["cases"])
    if failures:
        result["verdict"] = "reject"
        result["reasons"].append("failed_or_rejected_cases_present")
    languages = {}
    for language in sorted({row["language"] for row in expected.values()}):
        ids = [name for name, row in expected.items() if row["language"] == language]
        languages[language] = {
            "cases": len(ids),
            "total_characters": sum(expected[name]["reference_characters"] for name in ids),
            "baseline": {k: sum(checked[0][name][k] for name in ids) for k in COUNTS},
            "candidate": {k: sum(checked[1][name][k] for name in ids) for k in COUNTS},
        }
    return {
        **result,
        "cohort_sha256": fingerprint(lock),
        "languages": languages,
        "failures": failures,
        "metric": "speaker_assignment_characters",
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("manifest", "root", "lock", "baseline", "candidate", "output"):
        p.add_argument(f"--{name}", type=Path, required=True)
    args = p.parse_args()
    lock = load_json(args.lock)
    # Re-read the actual files, not only a self-declared lock digest in the reports.
    if prepare(load_json(args.manifest), args.root) != lock:
        raise ValueError("Cohort lock does not match current inputs")
    result = compare(lock, load_json(args.baseline), load_json(args.candidate))
    if args.output.exists():
        if load_json(args.output) != result:
            raise ValueError("Output differs; preserve existing evidence and use a new path")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"verdict": result["verdict"], "deploy_allowed": False}))
    raise SystemExit(0 if result["verdict"] == "improved_on_this_corpus" else 2)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, TypeError, AttributeError, OSError, wave.Error, EOFError):
        print(
            "Invalid comparison inputs or output; inspect private files locally.", file=sys.stderr
        )
        raise SystemExit(1) from None
