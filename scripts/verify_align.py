#!/usr/bin/env python3
"""stable-ts 정렬을 실제 음성에 돌려 보고 시각이 맞는지 잽니다.

make_speech_sample.py가 만든 음성은 문장 시작 시각을 우리가 알고 있습니다.
같은 대본을 타이밍 없이 넣고 정렬한 뒤, 나온 시각을 아는 값과 비교합니다.
모델을 실제로 내려받아 돌리므로 CI에서 필요할 때만 실행합니다.

    python scripts/verify_align.py --directory /audio --model tiny

판정 기준:

- 글자가 하나도 바뀌지 않을 것. 정렬은 전사가 아닙니다.
- 자막이 시간순이고 서로 겹치지 않을 것.
- 문장 시작 시각 오차가 한계(기본 3초) 안일 것. 실제 오차는 항상 출력합니다.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from worker.analysis import align_text

_SPACE = re.compile(r"\s+")


def squeeze(text: str) -> str:
    """공백을 뺀 글자열. 정렬은 공백 처리를 바꿀 수 있어도 글자는 못 바꿉니다."""
    return _SPACE.sub("", text)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--model", default="tiny")
    parser.add_argument("--language", default="ko")
    parser.add_argument("--tolerance", type=float, default=3.0)
    args = parser.parse_args()

    expected = json.loads((args.directory / "expected.json").read_text(encoding="utf-8"))
    sentences = expected["sentences"]
    script = " ".join(item["text"] for item in sentences)
    audio = args.directory / "sample.wav"

    print(f"모델 {args.model}, 음성 {audio}, 문장 {len(sentences)}개")
    cues = align_text(audio, script, model=args.model, language=args.language, device="cpu")
    print(f"정렬 결과 자막 {len(cues)}개\n")
    for cue in cues:
        print(f"  {cue.start:>6.2f} ~ {cue.end:>6.2f}  {cue.text}")

    problems: list[str] = []

    if squeeze("".join(c.text for c in cues)) != squeeze(script):
        problems.append("정렬 결과의 글자가 원본 대본과 다릅니다. 정렬이 전사처럼 동작했습니다.")

    for earlier, later in zip(cues, cues[1:], strict=False):
        if later.start < earlier.end - 0.001:
            problems.append(f"자막이 겹칩니다: {earlier.end:.2f} 다음에 {later.start:.2f}")
            break

    # 글자 위치 → 시각 지도를 만들어 문장 시작 시각을 찾습니다. 자막 나눔이
    # 문장 경계와 달라도 비교할 수 있습니다.
    spans: list[tuple[int, int, float]] = []
    offset = 0
    for cue in cues:
        length = len(squeeze(cue.text))
        spans.append((offset, offset + length, cue.start))
        offset += length

    print(f"\n{'문장':>4} {'실제 시작':>10} {'정렬 시작':>10} {'오차':>8}")
    worst = 0.0
    cursor = 0
    for index, item in enumerate(sentences, start=1):
        measured = next((start for begin, end, start in spans if end > cursor >= begin), None)
        if measured is None:
            problems.append(f"{index}번 문장의 시각을 찾지 못했습니다.")
            cursor += len(squeeze(item["text"]))
            continue
        gap = abs(measured - item["start"])
        worst = max(worst, gap)
        print(f"{index:>4} {item['start']:>9.2f}초 {measured:>9.2f}초 {gap:>7.2f}초")
        cursor += len(squeeze(item["text"]))

    print(f"\n문장 시작 시각 최대 오차 {worst:.2f}초 (한계 {args.tolerance:.1f}초)")
    if worst > args.tolerance:
        problems.append(f"문장 시작 오차 {worst:.2f}초가 한계를 넘습니다.")

    if problems:
        print("\n문제:")
        for problem in problems:
            print(f"- {problem}")
        return 1
    print("\n정렬이 글자를 지키고 문장 시각을 한계 안에서 맞췄습니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
