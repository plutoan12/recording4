"""Post-hoc human-reference coverage for frozen consensus gaps; never select candidates."""

import argparse
import math
from pathlib import Path

from prepare_conversation_evaluation import load_json
from run_sortformer_evaluation import sha256, write_private_json
from score_local_speech_retry import normalize


def coverage(gaps, words):
    rows = []
    if len({gap["id"] for gap in gaps}) != len(gaps):
        raise ValueError("Duplicate gap")
    for word in words:
        if (
            not all(math.isfinite(x) for x in (word["start"], word["end"]))
            or not word["start"] <= word["end"]
            or not isinstance(word["text"], str)
        ):
            raise ValueError("Invalid reference word")
    for gap in gaps:
        start, end = gap["start"], gap["end"]
        if not all(math.isfinite(x) for x in (start, end)) or not start < end:
            raise ValueError("Invalid gap")
        overlap = [word for word in words if max(start, word["start"]) < min(end, word["end"])]
        midpoint = [word for word in words if start <= (word["start"] + word["end"]) / 2 < end]
        rows.append(
            dict(
                id=gap["id"],
                duration=end - start,
                overlap_words=len(overlap),
                midpoint_words=len(midpoint),
                overlap_characters=sum(len(normalize(word["text"])) for word in overlap),
            )
        )
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ["gaps", "reference", "output"]:
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    gaps = load_json(args.gaps)
    reference = load_json(args.reference)
    if (
        gaps["selection_uses_reference"]
        or reference.get("word_timing_source") != "human_manual_AMI"
    ):
        raise ValueError("Require frozen prediction-only gaps and human manual timing")
    if gaps["source_sha256"] != reference["audio_sha256"]:
        raise ValueError("Different source audio")
    rows = coverage(gaps["audit"], reference["segments"])
    result = dict(
        rows=rows,
        totals=dict(
            gaps=len(rows),
            overlap_words=sum(row["overlap_words"] for row in rows),
            midpoint_words=sum(row["midpoint_words"] for row in rows),
            overlap_characters=sum(row["overlap_characters"] for row in rows),
        ),
        sha256={name: sha256(getattr(args, name)) for name in ["gaps", "reference"]},
        used_for_candidate_selection=False,
        deployment_allowed=False,
    )
    write_private_json(args.output, result)
    print(result["totals"])


if __name__ == "__main__":
    main()
