#!/usr/bin/env python3
"""Flag two saved diarizers' disagreements; never infer or relabel speakers.

All inputs/output are private. An identical audio SHA is required. Reference
annotations are intentionally not accepted by this review selection command.
"""

import argparse
import json
import re
from pathlib import Path

from prepare_conversation_evaluation import load_json
from run_sortformer_evaluation import write_private_json

from pipeline.speaker_disagreement import compare_turns, mark_reviews, overlap_retry_windows


def compare(baseline, candidate, reviews, duration):
    def digest(row):
        return row.get("source_sha256", row.get("sha256"))

    left, right = digest(baseline), digest(candidate)
    if not isinstance(left, str) or not re.fullmatch(r"[0-9a-f]{64}", left) or left != right:
        raise ValueError("Different or missing audio fingerprints")
    if not isinstance(reviews, dict) or digest(reviews) != left:
        raise ValueError("Reviews must declare the same audio fingerprint")
    for artifact in (baseline, candidate, reviews):
        if "duration_seconds" in artifact and artifact["duration_seconds"] != duration:
            raise ValueError("Recording duration mismatch")
    result = compare_turns(baseline["turns"], candidate["turns"], duration)
    result.update(
        source_sha256=left,
        duration_seconds=duration,
        retry_windows=overlap_retry_windows(result, duration),
        reviews=mark_reviews(reviews["reviews"], result),
        deploy_allowed=False,
    )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("baseline", "candidate", "reviews", "output"):
        parser.add_argument(f"--{name}", required=True, type=Path)
    parser.add_argument("--duration", required=True, type=float)
    args = parser.parse_args()
    result = compare(
        load_json(args.baseline), load_json(args.candidate), load_json(args.reviews), args.duration
    )
    write_private_json(args.output, result)
    print(
        json.dumps(
            dict(
                intervals=len(result["intervals"]),
                retry_windows=len(result["retry_windows"]),
                deploy_allowed=False,
            )
        )
    )


if __name__ == "__main__":
    main()
