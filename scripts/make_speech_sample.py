#!/usr/bin/env python3
"""espeak-ng 합성 음성으로 정렬 검증용 음성을 만듭니다.

문장을 하나씩 합성하고 사이에 무음을 넣습니다. 각 문장이 실제로 언제
시작하는지는 speech_sample.build_sample이 재서 기록합니다. 합성 음성이라
사람 목소리보다 불리한 조건입니다. 사람 목소리 검증은
fetch_korean_speech.py를 씁니다.

    python3 scripts/make_speech_sample.py --out /tmp/align
"""

from __future__ import annotations

import argparse
from pathlib import Path

from speech_sample import build_sample, run, to_mono16k

SENTENCES = [
    "안녕하세요 오늘은 자막 정렬을 검증합니다",
    "두 번째 문장입니다 조금 더 길게 말해 보겠습니다",
    "마지막 문장입니다 여기까지 듣느라 고생하셨습니다",
]


def synthesize(text: str, target: Path, *, voice: str, speed: int) -> Path:
    """espeak-ng로 한 문장을 합성해 16kHz 모노로 맞춥니다."""
    raw = target.with_name(f"raw-{target.name}")
    run(["espeak-ng", "-v", voice, "-s", str(speed), "-w", str(raw), text])
    return to_mono16k(raw, target)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--voice", default="ko")
    parser.add_argument("--speed", type=int, default=150)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    pieces = [
        (
            synthesize(sentence, args.out / f"part{index}.wav", voice=args.voice, speed=args.speed),
            sentence,
        )
        for index, sentence in enumerate(SENTENCES)
    ]
    build_sample(pieces, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
