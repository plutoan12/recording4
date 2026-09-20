#!/usr/bin/env python3
"""Compare speaker assignment reports; unchanged/rejected/missing is never a gain.

Exit 0 means improvement on exactly this corpus, not permission to deploy.
Exit 2 means a valid but non-improving/regressing candidate, 1 invalid evidence.
"""

import argparse
import json
from pathlib import Path

COUNTS = ("word_correct", "word_wrong", "word_unresolved")


def indexed(rows):
    result = {}
    if not isinstance(rows, list) or not rows:
        raise ValueError("Empty or invalid report")
    for row in rows:
        name = row["case"]
        if name in result:
            raise ValueError(f"Duplicate case: {name}")
        for key in (*COUNTS, "total_characters"):
            if type(row[key]) is not int or row[key] < 0:
                raise ValueError(f"Invalid count: {name}/{key}")
        if not row["total_characters"] or sum(row[k] for k in COUNTS) != row["total_characters"]:
            raise ValueError(f"Denominator mismatch: {name}")
        sha = row["sha256"]
        if (
            not isinstance(sha, str)
            or len(sha) != 64
            or any(c not in "0123456789abcdef" for c in sha)
        ):
            raise ValueError(f"Invalid audio digest: {name}")
        result[name] = row
    return result


def evaluate(baseline, candidate):
    before, after = indexed(baseline), indexed(candidate)
    if before.keys() != after.keys():
        raise ValueError("Case coverage changed; evaluate new corpus separately")
    reasons, cases = [], []
    for name, old in before.items():
        new = after[name]
        if old["sha256"] != new["sha256"] or old["total_characters"] != new["total_characters"]:
            raise ValueError(f"Input or denominator changed: {name}")
        delta = {key: new[key] - old[key] for key in COUNTS}
        cases.append(dict(case=name, delta=delta))
        if delta["word_wrong"] > 0:
            reasons.append(f"{name}: wrong_assignments_increased")
        if delta["word_correct"] < 0:
            reasons.append(f"{name}: correct_assignments_decreased")
    totals = {key: sum(row["delta"][key] for row in cases) for key in COUNTS}
    if totals["word_correct"] <= 0:
        reasons.append("no_additional_correct_assignments")
    return dict(
        schema=1,
        verdict="reject" if reasons else "improved_on_this_corpus",
        deploy_allowed=False,
        reasons=reasons,
        delta=totals,
        cases=cases,
    )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--baseline", type=Path, required=True)
    p.add_argument("--candidate", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    # Imported only by the CLI; evaluate() remains usable without script-path setup.
    from prepare_conversation_evaluation import digest, load_json

    def invalid(reason):
        return dict(schema=1, verdict="invalid", deploy_allowed=False, reasons=[reason])

    try:
        result = evaluate(load_json(args.baseline), load_json(args.candidate))
        result["inputs"] = {
            "baseline_sha256": digest(args.baseline),
            "candidate_sha256": digest(args.candidate),
        }
        code = 0 if result["verdict"] == "improved_on_this_corpus" else 2
    except (ValueError, KeyError, TypeError, OSError):
        # Do not copy filenames or untrusted report content into public logs.
        result, code = invalid("invalid_input"), 1
    try:
        if args.output.exists():
            if load_json(args.output) != result:
                raise ValueError("Existing evidence differs")
        else:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("x", encoding="utf-8") as stream:
                stream.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    except (ValueError, TypeError, OSError):
        result, code = invalid("output_conflict_or_unavailable"), 1
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(code)


if __name__ == "__main__":
    main()
