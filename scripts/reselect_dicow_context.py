"""Reapply core selection to a frozen dual-alignment audit without rerunning models."""

import argparse
from pathlib import Path

from align_dicow_context import select_core_words
from prepare_conversation_evaluation import load_json
from run_sortformer_evaluation import sha256, write_private_json
from score_local_speech_retry import normalize


def reselect(items, rows, baseline, aligned):
    groups = [items, rows, baseline, aligned["audit"]]
    ids = [{row["id"] for row in group} for group in groups]
    if not all(ids[0] == group_ids for group_ids in ids[1:]) or any(
        len(group) != len(group_ids) for group, group_ids in zip(groups, ids, strict=True)
    ):
        raise ValueError("Missing or duplicate input rows")
    raw_by_id = {row["id"]: row for row in rows}
    old_by_id = {row["id"]: row for row in baseline}
    audit_by_id = {row["id"]: row for row in aligned["audit"]}
    output = []
    audits = []
    for item in items:
        row = raw_by_id[item["id"]]
        old = old_by_id[item["id"]]
        frozen = audit_by_id[item["id"]]
        text = row["hypothesis"]
        selected_words = None
        selected = None
        status = "generation_truncated"
        if not row["generation_possibly_truncated"]:
            if not normalize(text):
                selected = ""
                status = "empty_decoding"
            else:
                selected_words, status = select_core_words(
                    text,
                    frozen["left"],
                    frozen["right"],
                    item["core_start"],
                    item["core_end"],
                    item["start"],
                    item["end"],
                )
                selected = (
                    " ".join(word["text"] for word in selected_words)
                    if selected_words is not None
                    else None
                )
        result = dict(row if selected is not None else old)
        result["hypothesis"] = selected if selected is not None else old["hypothesis"]
        result["context_alignment_status"] = status
        for key in ["errors", "cer", "reference_characters"]:
            result.pop(key, None)
        output.append(result)
        audits.append(
            dict(
                id=item["id"],
                status=status,
                fallback=selected is None,
                selected=selected_words if selected is not None and normalize(text) else [],
                left=frozen["left"],
                right=frozen["right"],
            )
        )
    return output, audits


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ["audio", "manifest", "rows", "baseline", "aligned", "output"]:
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    fingerprints = {
        name: sha256(getattr(args, name)) for name in ["audio", "manifest", "rows", "baseline"]
    }
    aligned = load_json(args.aligned)
    if aligned["sha256"] != fingerprints:
        raise ValueError("Frozen alignment inputs changed")
    if aligned["deploy_allowed"] or aligned["voice_identity_verified"]:
        raise ValueError("Expected candidate-only frozen alignment")
    output, audits = reselect(
        load_json(args.manifest),
        load_json(args.rows),
        load_json(args.baseline),
        aligned,
    )
    if any(sha256(getattr(args, name)) != digest for name, digest in fingerprints.items()):
        raise ValueError("Inputs changed")
    write_private_json(
        args.output,
        dict(
            rows=output,
            audit=audits,
            sha256=fingerprints,
            frozen_alignment_sha256=sha256(args.aligned),
            deploy_allowed=False,
            voice_identity_verified=False,
        ),
    )
    statuses = sorted({row["status"] for row in audits})
    print({status: sum(row["status"] == status for row in audits) for status in statuses})


if __name__ == "__main__":
    main()
