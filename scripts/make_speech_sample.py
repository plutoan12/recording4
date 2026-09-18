#!/usr/bin/env python3
"""정렬 검증용 한국어 음성을 만듭니다. 문장 경계 시각을 정확히 알기 위해서입니다.

espeak-ng로 문장을 하나씩 합성하고 사이에 정해진 길이의 무음을 넣습니다.
그래서 각 문장이 언제 시작하는지 우리가 이미 알고 있고, 정렬 결과를 그 값과
비교할 수 있습니다. 합성 음성이라 사람 목소리보다 불리한 조건입니다.

    python3 scripts/make_speech_sample.py --out /tmp/align

만들어지는 파일: sample.wav(16kHz 모노), expected.json(문장과 실제 시각).
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

SENTENCES = [
    "안녕하세요 오늘은 자막 정렬을 검증합니다",
    "두 번째 문장입니다 조금 더 길게 말해 보겠습니다",
    "마지막 문장입니다 여기까지 듣느라 고생하셨습니다",
]
GAP = 1.0


def run(command: list[str]) -> str:
    done = subprocess.run(command, capture_output=True, text=True, timeout=300)
    if done.returncode:
        raise RuntimeError(f"{command[0]} 실패: {done.stderr.strip()[:400]}")
    return done.stdout


def duration(path: Path) -> float:
    out = run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nw=1:nk=1",
            str(path),
        ]
    )
    return float(out.strip())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--voice", default="ko")
    parser.add_argument("--speed", type=int, default=150)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    silence = args.out / "silence.wav"
    run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=16000:cl=mono",
            "-t",
            str(GAP),
            str(silence),
        ]
    )

    parts: list[Path] = []
    expected: list[dict] = []
    cursor = GAP  # 앞에도 무음을 하나 둡니다. 시작부터 말이 나오지 않게 합니다.
    parts.append(silence)
    for index, sentence in enumerate(SENTENCES):
        raw = args.out / f"raw{index}.wav"
        part = args.out / f"part{index}.wav"
        run(["espeak-ng", "-v", args.voice, "-s", str(args.speed), "-w", str(raw), sentence])
        # 정렬에 넣을 오디오는 16kHz 모노로 통일합니다.
        run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(raw),
                "-ar",
                "16000",
                "-ac",
                "1",
                str(part),
            ]
        )
        length = duration(part)
        expected.append(
            {"text": sentence, "start": round(cursor, 3), "end": round(cursor + length, 3)}
        )
        cursor += length + GAP
        parts.append(part)
        parts.append(silence)

    listing = args.out / "concat.txt"
    listing.write_text("".join(f"file '{p.name}'\n" for p in parts), encoding="utf-8")
    sample = args.out / "sample.wav"
    run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(listing),
            "-ar",
            "16000",
            "-ac",
            "1",
            str(sample),
        ]
    )
    (args.out / "expected.json").write_text(
        json.dumps({"gap": GAP, "sentences": expected}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"{sample} ({duration(sample):.2f}초), 문장 {len(expected)}개")
    for item in expected:
        print(f"  {item['start']:>6.2f}초 ~ {item['end']:>6.2f}초  {item['text']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
