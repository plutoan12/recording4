#!/usr/bin/env python3
"""One-shot local quality gate and target-ASR review queue. Never deploys or publishes."""

import argparse
import hashlib
import json
from pathlib import Path

from check_speaker_quality import evaluate

from worker.target_review import propose_target_reviews, qualify_target_reviews


def run(
    baseline,
    candidate,
    reviews_dir,
    predictions,
    manifest,
    output,
    independent_evidence=None,
):
    output.mkdir(parents=True, exist_ok=True)
    (output / "summary.json").write_text(
        json.dumps(dict(status="running", deploy_allowed=False)), encoding="utf-8"
    )
    if independent_evidence is not None and not isinstance(independent_evidence, list):
        raise ValueError("Independent evidence must be a list")
    quality = evaluate(baseline, candidate)
    expected = {row["case"]: row for row in candidate}
    inputs = {row["id"]: row for row in manifest}
    if len(inputs) != len(manifest):
        raise ValueError("Duplicate manifest ID")
    groups = {}
    for row in predictions:
        name = row["id"].rsplit("-", 1)[0]
        if name not in expected:
            raise ValueError(f"Unknown evaluation case: {name}")
        if row["sha256"] != expected[name]["sha256"]:
            raise ValueError(f"Audio changed: {name}")
        if row.get("generation_possibly_truncated") is not False:
            raise ValueError(f"Incomplete or unverified decode: {row['id']}")
        item = inputs[row["id"]]
        group = groups.setdefault(name, [])
        if any(p["target"] == item["target"] for p in group):
            raise ValueError(f"Duplicate target: {name}")
        group.append(dict(target=item["target"], hypothesis=row["hypothesis"]))
    for name, group in groups.items():
        required_targets = {
            item["target"] for key, item in inputs.items() if key.rsplit("-", 1)[0] == name
        }
        if {item["target"] for item in group} != required_targets:
            raise ValueError(f"Incomplete target evidence: {name}")
    evidence_groups = {}
    for row in independent_evidence or []:
        if not isinstance(row, dict) or row.get("case") not in expected:
            raise ValueError("Unknown independent evidence case")
        if row["case"] not in groups:
            raise ValueError("Independent evidence has no target-ASR case")
        if row.get("source_sha256") != expected[row["case"]]["sha256"]:
            raise ValueError("Independent evidence audio changed")
        evidence_groups.setdefault(row["case"], []).append(
            {key: value for key, value in row.items() if key != "case"}
        )
    # Validate all input files before producing a batch; no partial success marker.
    prepared = []
    evidence_status = "evaluated" if independent_evidence is not None else "absent"
    for name, group in groups.items():
        # Case names originate from a report, but must never escape the output root.
        if Path(name).name != name or name in (".", ".."):
            raise ValueError("Invalid case name")
        original = json.loads((reviews_dir / (name + "-words.json")).read_text())
        reviewed = propose_target_reviews(original, group)
        if independent_evidence is not None:
            reviewed = qualify_target_reviews(reviewed, evidence_groups.get(name, []))
        for old_cue, new_cue in zip(original, reviewed, strict=True):
            for old_word, new_word in zip(old_cue["words"], new_cue["words"], strict=True):
                if any(
                    old_word.get(k) != new_word.get(k) for k in ("speaker", "text", "start", "end")
                ):
                    raise ValueError("Review generation attempted to change source assignments")
        prepared.append((name, reviewed))
    output.mkdir(parents=True, exist_ok=True)
    cases = []
    for name, reviewed in prepared:
        payload = json.dumps(reviewed, ensure_ascii=False, indent=2)
        (output / (name + "-review.json")).write_text(payload, encoding="utf-8")
        evidence = [
            w["target_asr_review"] for r in reviewed for w in r["words"] if "target_asr_review" in w
        ]
        cases.append(
            dict(
                case=name,
                review_sha256=hashlib.sha256(payload.encode()).hexdigest(),
                proposed_words=len(evidence),
                ambiguous_words=sum(len(x["candidates"]) > 1 for x in evidence),
                independent_evidence_status=evidence_status,
                independently_qualified_words=(
                    sum(x.get("qualified_for_reassignment", False) for x in evidence)
                    if evidence_status == "evaluated"
                    else None
                ),
            )
        )
    summary = dict(
        schema=2,
        quality=quality,
        cases=cases,
        changed_assignments=0,
        independent_evidence_status=evidence_status,
        status="review_required" if cases else "no_target_evidence",
        deploy_allowed=False,
    )
    (output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ["baseline", "candidate", "reviews-dir", "predictions", "manifest", "output"]:
        p.add_argument("--" + name, type=Path, required=True)
    p.add_argument("--independent-evidence", type=Path)
    a = p.parse_args()

    def load(path):
        return json.loads(path.read_text())

    a.output.mkdir(parents=True, exist_ok=True)
    (a.output / "summary.json").write_text(
        json.dumps(dict(status="running", deploy_allowed=False)), encoding="utf-8"
    )
    try:
        independent_evidence = None
        if a.independent_evidence:
            independent_evidence = load(a.independent_evidence)
            if not isinstance(independent_evidence, list):
                raise ValueError("Independent evidence must be a list")
        summary = run(
            load(a.baseline),
            load(a.candidate),
            a.reviews_dir,
            load(a.predictions),
            load(a.manifest),
            a.output,
            independent_evidence,
        )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        summary = dict(status="invalid", deploy_allowed=False, reason=str(exc))
        (a.output / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(summary, ensure_ascii=False))
        raise SystemExit(1) from exc

    print(json.dumps(summary, ensure_ascii=False))
    raise SystemExit(0 if summary["quality"]["verdict"] == "improved_on_this_corpus" else 2)


if __name__ == "__main__":
    main()
