"""Prepare conservative gap-only additions without changing baseline words."""

import argparse
from pathlib import Path

from prepare_conversation_evaluation import load_json
from run_sortformer_evaluation import sha256, write_private_json
from score_local_speech_retry import normalize


def overlaps(a, b, word):
    left, right = sorted((word["start"], word["end"]))
    if left == right:
        return a <= left <= b
    return max(a, left) < min(b, right)


def proposals(baseline, items, aligned):
    if len({x["id"] for x in items}) != len(items):
        raise ValueError("Duplicate item")
    by_id = {x["id"]: x for x in items}
    rows = {x["id"]: x for x in aligned["rows"]}
    candidates = []
    for audit in aligned["audit"]:
        if audit["status"] != "timing_consensus_only" or audit["fallback"]:
            continue
        item = by_id[audit["id"]]
        words = [
            dict(w)
            for w in audit["left"]
            if normalize(w["text"])
            and max(w["start"], item["core_start"]) < min(w["end"], item["core_end"])
        ]
        if normalize("".join(w["text"] for w in words)) != normalize(
            rows[item["id"]]["hypothesis"]
        ):
            raise ValueError("Selected words differ from aligned hypothesis")
        gap = [w for w in words if not any(overlaps(w["start"], w["end"], b) for b in baseline)]
        if not gap:
            continue
        a, b = min(w["start"] for w in gap), max(w["end"] for w in gap)
        # Do not combine separated holes across an existing baseline word.
        if any(overlaps(a, b, w) for w in baseline):
            continue
        candidates.append(
            dict(
                id=item["id"],
                target=item["target"],
                start=a,
                end=b,
                words=gap,
                turns=item.get("turns", []),
            )
        )
    return candidates


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for key in ["baseline", "manifest", "aligned", "output"]:
        p.add_argument("--" + key, type=Path, required=True)
    args = p.parse_args()
    base = load_json(args.baseline)
    aligned = load_json(args.aligned)
    if aligned["sha256"]["manifest"] != sha256(args.manifest):
        raise ValueError("Alignment manifest changed")
    if base["sha256"]["audio"] != aligned["sha256"]["audio"]:
        raise ValueError("Different audio")
    result = dict(
        source_sha256=base["sha256"]["audio"],
        baseline=base["original"],
        candidates=proposals(base["original"], load_json(args.manifest), aligned),
        sha256={k: sha256(getattr(args, k)) for k in ["baseline", "manifest", "aligned"]},
        selection_uses_reference=False,
        deploy_allowed=False,
    )
    write_private_json(args.output, result)
    print("candidate groups", len(result["candidates"]))


if __name__ == "__main__":
    main()
