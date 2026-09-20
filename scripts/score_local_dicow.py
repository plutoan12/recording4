"""Score every fixed local DiCoW slot, including missing speakers and empty references."""

import argparse
from collections import Counter
from pathlib import Path

from prepare_conversation_evaluation import load_json
from run_sortformer_evaluation import sha256, write_private_json
from score_local_speech_retry import normalize


def distance(left, right):
    previous = list(range(len(right) + 1))
    for i, a in enumerate(left, 1):
        current = [i]
        for j, b in enumerate(right, 1):
            current.append(min(previous[j] + 1, current[-1] + 1, previous[j - 1] + (a != b)))
        previous = current
    return previous[-1]


def evaluate(slots, rows):
    expected = [s["row_id"] for s in slots if s["row_id"] is not None]
    if len(expected) != len(set(expected)) or len(rows) != len({r["id"] for r in rows}):
        raise ValueError("Duplicate decode row")
    if set(expected) != {r["id"] for r in rows}:
        raise ValueError("Incomplete or extra decode rows")
    by_id = {r["id"]: r for r in rows}
    models = sorted({s["model"] for s in slots})
    if len(models) != 2:
        raise ValueError("Exactly two model inputs required")
    # The same windows and reference slots must be scored for both model masks.
    cohorts = [
        Counter(
            (s["window"], s["reference"], s["boundary_words"]) for s in slots if s["model"] == m
        )
        for m in models
    ]
    if cohorts[0] != cohorts[1]:
        raise ValueError("Different scoring denominators")
    result = {}
    for model in models:
        counts = dict(
            reference_characters=0,
            errors=0,
            empty_reference_insertions=0,
            missing_target_characters=0,
            boundary_words=0,
            truncated_rows=0,
        )
        for slot in (s for s in slots if s["model"] == model):
            reference = normalize(slot["reference"])
            row = by_id[slot["row_id"]] if slot["row_id"] is not None else None
            hypothesis = normalize(row["hypothesis"]) if row else ""
            errors = distance(reference, hypothesis)
            counts["reference_characters"] += len(reference)
            counts["errors"] += errors
            counts["boundary_words"] += slot["boundary_words"]
            counts["empty_reference_insertions"] += errors if not reference else 0
            counts["missing_target_characters"] += len(reference) if row is None else 0
            counts["truncated_rows"] += bool(row and row["generation_possibly_truncated"])
        counts["cer"] = (
            counts["errors"] / counts["reference_characters"]
            if counts["reference_characters"]
            else None
        )
        result[model] = counts
    return dict(
        models=result,
        scoring_slots=len(slots),
        decode_rows=len(rows),
        scope="conservative_local_CER_with_clipped_words_not_full_video_accuracy",
        automatic_reassignment=False,
        deploy_allowed=False,
    )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ["slots", "rows", "protocol", "output"]:
        p.add_argument("--" + name, type=Path, required=True)
    args = p.parse_args()
    protocol = load_json(args.protocol)
    if protocol["slots_sha256"] != sha256(args.slots):
        raise ValueError("Scoring slots changed")
    rows = load_json(args.rows)
    if any(r["sha256"] != protocol["audio_sha256"] for r in rows):
        raise ValueError("Audio changed")
    result = evaluate(load_json(args.slots), rows)
    result["sha256"] = {k: sha256(getattr(args, k)) for k in ["slots", "rows", "protocol"]}
    write_private_json(args.output, result)
    print(result)


if __name__ == "__main__":
    main()
