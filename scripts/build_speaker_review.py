#!/usr/bin/env python3
"""Build a private, standalone reviewer without changing received annotations."""

import argparse
import hashlib
import json
import math
import os
import wave
from pathlib import Path

from prepare_conversation_evaluation import load_json

HUMAN_FIELDS = {"human_speakers", "human_overlap", "human_confidence", "reviewer"}


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def finite(value):
    try:
        return type(value) in (float, int) and math.isfinite(value)
    except OverflowError:
        return False


def prepare(template_path, reviewed_path):
    result = inspect_review(template_path, load_json(reviewed_path))
    result["received_sha256"] = sha(reviewed_path)
    return result


def same_json(left, right):
    """JSON number representations may differ; booleans are never numbers."""
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(same_json(v, right[k]) for k, v in left.items())
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(
            same_json(a, b) for a, b in zip(left, right, strict=True)
        )
    return left == right


def inspect_review(template_path, reviewed):
    template = load_json(template_path)
    if not isinstance(template, dict) or not isinstance(reviewed, dict):
        raise ValueError("Expected review objects")
    if (
        type(template.get("schema")) is not int
        or template["schema"] != 1
        or type(reviewed.get("schema")) is not int
        or reviewed["schema"] != 1
    ):
        raise ValueError("Unsupported template")
    if not same_json(
        {k: v for k, v in template.items() if k != "items"},
        {k: v for k, v in reviewed.items() if k != "items"},
    ):
        raise ValueError("Review provenance changed")
    original, items = template.get("items"), reviewed.get("items")
    if not isinstance(original, list) or not original or not isinstance(items, list):
        raise ValueError("Missing review items")
    if len(original) != len(items):
        raise ValueError("Review cohort changed")
    measurements, seen = {}, set()
    for base, item in zip(original, items, strict=True):
        if not isinstance(base, dict) or not isinstance(item, dict):
            raise ValueError("Invalid review item")
        if not HUMAN_FIELDS <= item.keys():
            raise ValueError("Missing annotation fields")
        if not same_json(
            {k: v for k, v in base.items() if k not in HUMAN_FIELDS},
            {k: v for k, v in item.items() if k not in HUMAN_FIELDS},
        ):
            raise ValueError("Candidate metadata changed")
        index = item.get("review_id")
        if type(index) is not int or index in seen:
            raise ValueError("Invalid candidate ID")
        seen.add(index)
        speakers = item.get("human_speakers")
        if speakers is not None and (
            not isinstance(speakers, list)
            or not all(isinstance(s, str) for s in speakers)
            or len(set(speakers)) != len(speakers)
            or not set(speakers) <= {"speaker_0", "speaker_1", "unknown", "multiple"}
            or (bool(set(speakers) & {"unknown", "multiple"}) and len(speakers) != 1)
        ):
            raise ValueError("Invalid speaker annotation")
        overlap, confidence = item.get("human_overlap"), item.get("human_confidence")
        if overlap is not None and type(overlap) is not bool:
            raise ValueError("Invalid overlap annotation")
        if confidence is not None and (not finite(confidence) or not 0 <= confidence <= 1):
            raise ValueError("Invalid confidence")
        if item.get("reviewer") is not None and not isinstance(item["reviewer"], str):
            raise ValueError("Invalid reviewer")
        times = [
            item.get(k) for k in ("audio_start", "candidate_start", "candidate_end", "audio_end")
        ]
        if (
            not all(finite(t) for t in times)
            or not 0 <= times[0] <= times[1] < times[2] <= times[3]
        ):
            raise ValueError("Invalid candidate timeline")
        name = item.get("audio_file")
        if not isinstance(name, str) or Path(name).name != name or Path(name).suffix != ".wav":
            raise ValueError("Invalid audio filename")
        audio = template_path.parent / name
        if audio.resolve().parent != template_path.parent.resolve():
            raise ValueError("Audio must be inside the review pack")
        with wave.open(str(audio), "rb") as wav:
            count, rate = wav.getnframes(), wav.getframerate()
            frame_bytes = wav.getnchannels() * wav.getsampwidth()
            if rate != 16000 or wav.getnchannels() != 1 or count <= 0:
                raise ValueError("Expected nonempty 16kHz mono WAV")
            remaining = count
            while remaining:
                batch = min(remaining, 65536)
                if len(wav.readframes(batch)) != batch * frame_bytes:
                    raise ValueError("Truncated WAV payload")
                remaining -= batch
        duration = count / rate
        measurements[str(index)] = {
            "sha256": sha(audio),
            "duration": duration,
            "sample_rate": rate,
            "declared_duration_matches": abs(duration - (times[3] - times[0])) <= 1 / rate,
            "candidate_fully_audible": times[2] <= times[0] + duration,
        }
    return {
        "received": reviewed,
        "measurements": measurements,
        "template_sha256": sha(template_path),
    }


def build(template_path, reviewed_path, output):
    if output.parent.resolve() != template_path.parent.resolve() or output.suffix != ".html":
        raise ValueError("Write a new HTML next to the template")
    payload = prepare(template_path, reviewed_path)
    layout = Path(__file__).parent / "assets" / "speaker_review.html"
    encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False).replace("<", "\\u003c")
    page = layout.read_text(encoding="utf-8").replace("__REVIEW_DATA__", encoded)
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(page)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--reviewed", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        build(args.template, args.reviewed, args.output)
    except (ValueError, OSError, EOFError, wave.Error):
        print("검수 입력·WAV·출력 경로를 확인하세요. 기존 출력 파일은 덮어쓰지 않습니다.")
        return 1
    print("검수 화면 생성 완료. 입력 라벨의 의미·화자 대응·정확도는 별도 확인이 필요합니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
