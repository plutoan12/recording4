"""Expand decoding context while preserving every original DiCoW evaluation core."""

import argparse
from pathlib import Path

from prepare_conversation_evaluation import load_json
from run_sortformer_evaluation import sha256, write_private_json


def expand(items, duration=120):
    result = []
    for item in items:
        a, b = item["start"], item["end"]
        if not 0 <= a < b <= duration or b - a + 6 > 30:
            raise ValueError("Invalid core or too much context")
        result.append(
            dict(item, core_start=a, core_end=b, start=max(0, a - 3), end=min(duration, b + 3))
        )
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    protocol = load_json(args.source / "protocol.json")
    if sha256(args.source / "manifest.json") != protocol["manifest_sha256"]:
        raise ValueError("Original manifest changed")
    items = expand(load_json(args.source / "manifest.json"))
    args.output.mkdir(mode=0o700, exist_ok=False)
    write_private_json(args.output / "manifest.json", items)
    write_private_json(
        args.output / "protocol.json",
        dict(
            extra_context_seconds=3,
            original_protocol_sha256=sha256(args.source / "protocol.json"),
            reference_slots_sha256=protocol["slots_sha256"],
            time_agreement_seconds=0.5,
            alignment_sources=["stable-ts", "whisperx"],
            failure_policy="retain original short-window hypothesis; record rejection",
            selection_policy="both aligners must overlap unchanged core, whole intersecting words",
            deployment_allowed=False,
        ),
    )


if __name__ == "__main__":
    main()
