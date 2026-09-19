#!/usr/bin/env python3
"""실제 STT 전사 품질을 재고 회귀를 막습니다.

지금까지 STT는 "불러오기와 설치"만 확인했습니다. 실제로 무엇을 받아쓰는지는
잰 적이 없습니다. 정렬(align)은 대본이 있을 때 시각만 붙이는 일이라 전사
품질과 다릅니다. 대본이 없는 원본은 이 경로를 탑니다.

    python scripts/verify_transcribe.py --directory /audio --model small

speech_sample이 만든 음성은 문장마다 원문을 알고 있습니다. 그 원문과 받아쓴
글자를 글자 오류율(CER)로 비교합니다.

**숫자 표기에 주의합니다.** 낭독 데이터의 원문은 숫자를 한글로 적고("이천 십
팔 년") 모델은 아라비아 숫자로 적습니다("2018년"). 같은 말이라도 글자가 달라
CER이 올라갑니다. 그래서 한계값은 품질 목표가 아니라 회귀 감시용 상한입니다.
실제 값과 문장별 원문·전사를 항상 출력하니 수치보다 그쪽을 먼저 보세요.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

from worker.analysis import transcribe

_KEEP = re.compile(r"[\s\W_]+", re.UNICODE)


def squeeze(text: str) -> str:
    """비교용 글자열. 공백과 문장부호를 빼고 한글을 정규화합니다.

    받아쓰기는 띄어쓰기와 문장부호를 원문과 다르게 찍습니다. 그것까지 오류로
    세면 실제로 잘못 들은 양을 알 수 없습니다.
    """
    return _KEEP.sub("", unicodedata.normalize("NFC", text))


def distance(left: str, right: str) -> int:
    """두 글자열 사이의 편집 거리(삽입·삭제·교체)."""
    if not left:
        return len(right)
    previous = list(range(len(right) + 1))
    for index, source in enumerate(left, start=1):
        current = [index]
        for position, target in enumerate(right, start=1):
            current.append(
                min(
                    previous[position] + 1,  # 삭제
                    current[position - 1] + 1,  # 삽입
                    previous[position - 1] + (source != target),  # 교체
                )
            )
        previous = current
    return previous[-1]


def cer(reference: str, hypothesis: str) -> float:
    """글자 오류율. 원문 글자 수로 나눕니다. 원문이 비면 0입니다."""
    left, right = squeeze(reference), squeeze(hypothesis)
    return 0.0 if not left else distance(left, right) / len(left)


def pair_by_time(sentences: list[dict], cues: list) -> list[tuple[dict, str]]:  # noqa: ANN001
    """문장마다 시간이 겹치는 전사를 모읍니다.

    전사는 문장 수와 다르게 나뉩니다. 문장 경계로 자르지 말고 겹치는 시간으로
    모아야 어느 문장을 못 알아들었는지 볼 수 있습니다.
    """
    paired: list[tuple[dict, str]] = []
    for item in sentences:
        parts = [
            cue.text
            for cue in cues
            if min(cue.end, item["end"]) - max(cue.start, item["start"]) > 0.001
        ]
        paired.append((item, " ".join(parts)))
    return paired


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    # 운영 기본값(R4_WHISPER_MODEL)과 같은 모델로 재야 의미가 있습니다.
    parser.add_argument("--model", default="small")
    parser.add_argument("--language", default="ko")
    # 품질 목표가 아니라 회귀 감시용 상한입니다. 숫자 표기 차이가 섞여 있습니다.
    parser.add_argument("--max-cer", type=float, default=0.35)
    args = parser.parse_args()

    expected = json.loads((args.directory / "expected.json").read_text(encoding="utf-8"))
    sentences = expected["sentences"]
    audio = args.directory / "sample.wav"

    print(f"모델 {args.model}, 음성 {audio}, 문장 {len(sentences)}개")
    cues = transcribe(audio, model=args.model, language=args.language, device="cpu")
    print(f"전사 결과 자막 {len(cues)}개")
    for cue in cues:
        print(f"  {cue.start:>6.2f} ~ {cue.end:>6.2f}  {cue.text}")

    problems: list[str] = []
    if not cues:
        problems.append("전사 결과가 비었습니다. 음성이나 모델을 확인하세요.")

    print("\n문장별 비교")
    for index, (item, heard) in enumerate(pair_by_time(sentences, cues), start=1):
        rate = cer(item["text"], heard)
        print(f"  {index}. CER {rate:>6.1%}")
        print(f"     원문: {item['text']}")
        print(f"     전사: {heard or '(없음)'}")

    reference = " ".join(item["text"] for item in sentences)
    heard_all = " ".join(cue.text for cue in cues)
    overall = cer(reference, heard_all)
    print(f"\n전체 CER {overall:.1%} (원문 {len(squeeze(reference))}자, 한계 {args.max_cer:.0%})")
    if overall > args.max_cer:
        problems.append(
            f"전사 글자 오류율 {overall:.1%}이 한계 {args.max_cer:.0%}를 넘습니다. "
            "숫자 표기 차이인지 실제 오인식인지 위 문장별 비교로 확인하세요."
        )

    if problems:
        print("\n문제:")
        for problem in problems:
            print(f"- {problem}")
        return 1
    print("\n전사가 한계 안입니다. 수치보다 위 문장별 비교를 먼저 보세요.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
