#!/usr/bin/env python3
"""Preserve a v2 review and audit its provenance without approving scores."""

import argparse
import hashlib
import json
import os
import wave
from pathlib import Path

from build_speaker_review import inspect_review, prepare, same_json, sha
from prepare_conversation_evaluation import load_json


def audit(template, parent_review, submission, source_video):
    parent = prepare(template, parent_review)
    raw = submission.read_bytes()
    reviewed = load_json(submission)
    if raw != submission.read_bytes():
        raise ValueError("Submission changed while reading")
    if not isinstance(reviewed, dict) or not isinstance(reviewed.get("items"), list):
        raise ValueError("Expected review object")
    expected_ui = {
        "version": 2,
        "template_sha256": parent["template_sha256"],
        "received_sha256": parent["received_sha256"],
        "measurements": parent["measurements"],
        "score_approved": False,
    }
    if not same_json(reviewed.get("review_ui"), expected_ui):
        raise ValueError("Review origin or audio evidence changed")
    if sha(source_video) != parent["received"].get("source_video_sha256"):
        raise ValueError("Source video changed")
    # Validate the additional v2 fields first, then reuse the v1 label contract.
    normalized = {k: v for k, v in reviewed.items() if k != "review_ui"}
    normalized["items"] = []
    scopes = {}
    for item in reviewed["items"]:
        if not isinstance(item, dict) or "annotation_scope" not in item:
            raise ValueError("Missing annotation scope")
        scope = item["annotation_scope"]
        if scope not in (None, "candidate", "context", "uncertain"):
            raise ValueError("Invalid annotation scope")
        index = item.get("review_id")
        if type(index) is not int or index in scopes:
            raise ValueError("Invalid candidate ID")
        scopes[index] = scope
        normalized["items"].append({k: v for k, v in item.items() if k != "annotation_scope"})
    checked = inspect_review(template, normalized)
    if not same_json(checked["measurements"], parent["measurements"]):
        raise ValueError("Audio changed during audit")
    entries = []
    for item in normalized["items"]:
        index = item["review_id"]
        measurement = checked["measurements"][str(index)]
        reasons = []
        if not item["human_speakers"]:
            reasons.append("missing_speaker")
        elif "unknown" in item["human_speakers"]:
            reasons.append("unknown_speaker")
        elif "multiple" in item["human_speakers"]:
            reasons.append("multiple_speaker_identities_unconfirmed")
        if item["human_overlap"] is None:
            reasons.append("missing_overlap")
        if item["human_confidence"] is None:
            reasons.append("missing_confidence")
        if not (item["reviewer"] or "").strip():
            reasons.append("missing_reviewer")
        if scopes[index] != "candidate":
            reasons.append("candidate_scope_unconfirmed")
        if not measurement["candidate_fully_audible"]:
            reasons.append("candidate_audio_incomplete")
        if not measurement["declared_duration_matches"]:
            reasons.append("context_duration_mismatch")
        entries.append({"review_id": index, "scope": scopes[index], "reasons": reasons})
    report = {
        "schema": 1,
        "status": "review_received_not_scored",
        "template_sha256": parent["template_sha256"],
        "parent_review_sha256": parent["received_sha256"],
        "submission_sha256": hashlib.sha256(raw).hexdigest(),
        "source_video_sha256": parent["received"]["source_video_sha256"],
        "measurements": checked["measurements"],
        "candidate_count": len(entries),
        "candidates_with_pending_issues": sum(bool(x["reasons"]) for x in entries),
        "items": entries,
        "remaining_requirements": ["speaker_identity_mapping", "full_timed_reference_for_der_cer"],
        "accuracy": None,
        "der": None,
        "cer": None,
        "deploy_allowed": False,
    }
    return raw, report


def import_review(template, parent_review, submission, source_video, output):
    raw, report = audit(template, parent_review, submission, source_video)
    output.mkdir(mode=0o700, exist_ok=False)
    for name, data in (
        ("labels.received.json", raw),
        ("audit.json", (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode()),
    ):
        fd = os.open(output / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("template", "parent-review", "submission", "source-video", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    try:
        report = import_review(
            args.template, args.parent_review, args.submission, args.source_video, args.output
        )
    except (ValueError, OSError, EOFError, wave.Error):
        print("검수 제출본·기준 파일·음원·새 출력 폴더를 확인하세요. 채점하지 않았습니다.")
        return 1
    print(f"검수 {report['candidate_count']}개 수신·보존 완료. 정확도 채점·운영 승인은 별도입니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
