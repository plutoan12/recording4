#!/usr/bin/env python3
"""One-shot local quality gate and target-ASR review queue. Never deploys or publishes."""

import argparse
import hashlib
import json
from pathlib import Path

from check_speaker_quality import evaluate

from worker.target_review import propose_target_reviews


def run(baseline, candidate, reviews_dir, predictions, manifest, output):
    output.mkdir(parents=True, exist_ok=True)
    (output / "summary.json").write_text(json.dumps(dict(status="running", deploy_allowed=False)))
    quality = evaluate(baseline, candidate)
    expected = {row["case"]: row for row in candidate}
    inputs = {row["id"]: row for row in manifest}
    if len(inputs) != len(manifest):
        raise ValueError("Duplicate manifest ID")
    groups = {}
    for row in predictions:
        name = row["id"].rsplit("-", 1)[0]
        if name not in expected:
            continue
        if row["sha256"] != expected[name]["sha256"]:
            raise ValueError(f"Audio changed: {name}")
        item = inputs[row["id"]]
        group = groups.setdefault(name, [])
        if any(p["target"] == item["target"] for p in group):
            raise ValueError(f"Duplicate target: {name}")
        group.append(dict(target=item["target"], hypothesis=row["hypothesis"]))
    # Validate all input files before producing a batch; no partial success marker.
    prepared = []
    for name, group in groups.items():
        # Case names originate from a report, but must never escape the output root.
        if Path(name).name != name or name in (".", ".."):
            raise ValueError("Invalid case name")
        original = json.loads((reviews_dir / (name + "-words.json")).read_text())
        reviewed = propose_target_reviews(original, group)
        prepared.append((name, reviewed))
    output.mkdir(parents=True, exist_ok=True)
    cases = []
    for name, reviewed in prepared:
        payload = json.dumps(reviewed, ensure_ascii=False, indent=2)
        (output / (name + "-review.json")).write_text(payload)
        evidence = [
            w["target_asr_review"] for r in reviewed for w in r["words"] if "target_asr_review" in w
        ]
        cases.append(
            dict(
                case=name,
                review_sha256=hashlib.sha256(payload.encode()).hexdigest(),
                proposed_words=len(evidence),
                ambiguous_words=sum(len(x["candidates"]) > 1 for x in evidence),
            )
        )
    summary = dict(
        schema=1,
        quality=quality,
        cases=cases,
        changed_assignments=0,
        status="review_required" if cases else "no_target_evidence",
        deploy_allowed=False,
    )
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ["baseline", "candidate", "reviews-dir", "predictions", "manifest", "output"]:
        p.add_argument("--" + name, type=Path, required=True)
    a = p.parse_args()

    def load(path):
        return json.loads(path.read_text())

    a.output.mkdir(parents=True, exist_ok=True)
    (a.output / "summary.json").write_text(json.dumps(dict(status="running", deploy_allowed=False)))
    try:
        summary = run(
            load(a.baseline),
            load(a.candidate),
            a.reviews_dir,
            load(a.predictions),
            load(a.manifest),
            a.output,
        )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        summary = dict(status="invalid", deploy_allowed=False, reason=str(exc))
        (a.output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
        print(json.dumps(summary, ensure_ascii=False))
        raise SystemExit(1) from exc

    print(json.dumps(summary, ensure_ascii=False))
    raise SystemExit(0 if summary["quality"]["verdict"] == "improved_on_this_corpus" else 2)


if __name__ == "__main__":
    main()
