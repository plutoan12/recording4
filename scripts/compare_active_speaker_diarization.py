#!/usr/bin/env python3
"""Compare private active-face logits with audio diarization for review triage.

The input is a sanitized JSON export: no face boxes, images, audio or text. The
result measures model disagreement only and must not be presented as accuracy.
"""

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

from prepare_conversation_evaluation import load_json


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def finite(value):
    return not isinstance(value, bool) and isinstance(value, int | float) and math.isfinite(value)


def _fraction(numerator, denominator):
    return numerator / denominator if denominator else None


def _intervals(mask, frame_rate):
    intervals = []
    start = None
    for frame, active in enumerate(mask + [False]):
        if active and start is None:
            start = frame
        elif not active and start is not None:
            intervals.append({"start": start / frame_rate, "end": frame / frame_rate})
            start = None
    return intervals


def compare(active, diarization, *, active_sha256, diarization_sha256):
    if (
        not isinstance(active, dict)
        or type(active.get("schema")) is not int
        or active["schema"] != 1
    ):
        raise ValueError("Invalid active-speaker evidence")
    if active.get("score_kind") != "class_1_logit" or not finite(active.get("active_threshold")):
        raise ValueError("Unsupported active-speaker score")
    frame_rate = active.get("frame_rate")
    frame_count = active.get("frame_count")
    if (
        not finite(frame_rate)
        or frame_rate <= 0
        or isinstance(frame_count, bool)
        or not isinstance(frame_count, int)
        or frame_count <= 0
    ):
        raise ValueError("Invalid active-speaker timeline")
    for name in ("source_video_sha256", "source_audio_sha256", "model_revision"):
        if not isinstance(active.get(name), str) or not active[name].strip():
            raise ValueError("Missing active-speaker provenance")
    tracks = active.get("tracks")
    if not isinstance(tracks, list) or not tracks:
        raise ValueError("Missing active-speaker tracks")

    visual_count = [0] * frame_count
    visual_unknown = [False] * frame_count
    unscored_track_frames = 0
    threshold = float(active["active_threshold"])
    for track in tracks:
        if not isinstance(track, dict):
            raise ValueError("Invalid active-speaker track")
        frames, scores = track.get("frames"), track.get("scores")
        if not isinstance(frames, list) or not isinstance(scores, list) or not frames:
            raise ValueError("Invalid active-speaker track")
        if len(scores) > len(frames):
            raise ValueError("Scores extend beyond track")
        if any(
            isinstance(frame, bool) or not isinstance(frame, int) or not 0 <= frame < frame_count
            for frame in frames
        ) or any(right <= left for left, right in zip(frames, frames[1:], strict=False)):
            raise ValueError("Invalid active-speaker frame")
        if not all(finite(score) for score in scores):
            raise ValueError("Invalid active-speaker score")
        for frame, score in zip(frames, scores, strict=False):
            if score >= threshold:
                visual_count[frame] += 1
        for frame in frames[len(scores) :]:
            visual_unknown[frame] = True
            unscored_track_frames += 1

    if (
        not isinstance(diarization, dict)
        or type(diarization.get("schema")) is not int
        or diarization["schema"] != 1
    ):
        raise ValueError("Invalid diarization evidence")
    if diarization.get("source_sha256") != active["source_audio_sha256"]:
        raise ValueError("Audio evidence does not match")
    revision = diarization.get("model_revision")
    turns = diarization.get("turns")
    if not isinstance(revision, str) or not revision.strip() or not isinstance(turns, list):
        raise ValueError("Missing diarization provenance")
    duration = frame_count / frame_rate
    audio_speakers = [set() for _ in range(frame_count)]
    for turn in turns:
        if (
            not isinstance(turn, dict)
            or not isinstance(turn.get("speaker"), str)
            or not turn["speaker"].strip()
            or not finite(turn.get("start"))
            or not finite(turn.get("end"))
            or not 0 <= turn["start"] < turn["end"] <= duration
        ):
            raise ValueError("Invalid diarization turn")
        # Compare modalities at each video frame's center. Expanding both turn
        # edges with floor/ceil would manufacture overlap at speaker changes.
        for frame in range(frame_count):
            center = (frame + 0.5) / frame_rate
            if turn["start"] <= center < turn["end"]:
                audio_speakers[frame].add(turn["speaker"].strip())

    audio_count = [len(speakers) for speakers in audio_speakers]

    visual_active = sum(count >= 1 for count in visual_count)
    visual_overlap = sum(count >= 2 for count in visual_count)
    audio_active = sum(count >= 1 for count in audio_count)
    audio_overlap = sum(count >= 2 for count in audio_count)
    overlap_agreement = sum(
        visual >= 2 and audio >= 2 for visual, audio in zip(visual_count, audio_count, strict=True)
    )
    unknown_frames = sum(visual_unknown)
    visual_overlap_only = [
        visual >= 2 and audio < 2 for visual, audio in zip(visual_count, audio_count, strict=True)
    ]
    audio_overlap_only = [
        audio >= 2 and visual < 2 for visual, audio in zip(visual_count, audio_count, strict=True)
    ]
    unknown_visual = list(visual_unknown)
    return {
        "schema": 1,
        "metric": "active_speaker_audio_disagreement",
        "source_video_sha256": active["source_video_sha256"],
        "source_audio_sha256": active["source_audio_sha256"],
        "active_evidence_sha256": active_sha256,
        "diarization_evidence_sha256": diarization_sha256,
        "active_speaker_model_revision": active["model_revision"].strip(),
        "diarization_model_revision": revision.strip(),
        "score_kind": "class_1_logit",
        "active_threshold": threshold,
        "frame_rate": frame_rate,
        "evaluated_frames": frame_count,
        "evaluated_seconds": duration,
        "face_tracks": len(tracks),
        "unscored_track_frames": unscored_track_frames,
        "visual_unknown_frames": unknown_frames,
        "visual_unknown_seconds": unknown_frames / frame_rate,
        "visual_active_seconds_lower_bound": visual_active / frame_rate,
        "visual_overlap_seconds_lower_bound": visual_overlap / frame_rate,
        "audio_speech_seconds": audio_active / frame_rate,
        "audio_overlap_seconds": audio_overlap / frame_rate,
        "overlap_agreement_seconds_lower_bound": overlap_agreement / frame_rate,
        "visual_overlap_supported_by_audio_fraction": _fraction(overlap_agreement, visual_overlap),
        "audio_overlap_supported_by_visual_fraction_lower_bound": _fraction(
            overlap_agreement, audio_overlap
        ),
        "review_intervals": {
            "visual_overlap_without_audio_overlap": _intervals(visual_overlap_only, frame_rate),
            "audio_overlap_without_visual_overlap": _intervals(audio_overlap_only, frame_rate),
            "visual_unscored": _intervals(unknown_visual, frame_rate),
        },
        "human_ground_truth": False,
        "accuracy_claim_allowed": False,
        "deploy_allowed": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("active", "diarization", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    result = compare(
        load_json(args.active),
        load_json(args.diarization),
        active_sha256=sha256(args.active),
        diarization_sha256=sha256(args.diarization),
    )
    payload = json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
    if args.output.exists():
        if args.output.read_text(encoding="utf-8") != payload:
            raise ValueError("Different existing output; use a new path")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(json.dumps({"accuracy_claim_allowed": False, "deploy_allowed": False}))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, TypeError, OverflowError, OSError):
        print("Invalid active-speaker comparison inputs or output.", file=sys.stderr)
        raise SystemExit(1) from None
