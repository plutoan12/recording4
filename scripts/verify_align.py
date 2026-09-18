#!/usr/bin/env python3
"""stable-ts 정렬을 실제 음성에 돌려 보고 시각이 맞는지 잽니다.

make_speech_sample.py가 만든 음성은 문장 시작 시각을 우리가 알고 있습니다.
같은 대본을 타이밍 없이 넣고 정렬한 뒤, 나온 시각을 아는 값과 비교합니다.
모델을 실제로 내려받아 돌리므로 CI에서 필요할 때만 실행합니다.

    python scripts/verify_align.py --directory /audio --model tiny

대본은 한 줄에 한 문장씩 넣습니다. 정렬은 한 덩어리로 돌리고 줄 나누기는
단어 시각으로 우리가 하므로, 문장별 시각을 곧바로 비교할 수 있습니다.

판정 기준:

- 글자가 하나도 바뀌지 않을 것. 정렬은 전사가 아닙니다.
- 자막이 시간순이고 서로 겹치지 않을 것.
- 자막마다 시작 시각 오차가 한계(기본 1초) 안일 것. 실제 오차는 항상 출력합니다.
- 문장 경계가 자막 경계로 남을 것. 여러 문장이 한 자막으로 합쳐지면 보고합니다.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from pipeline.alignment import cues_for_lines
from worker.analysis import align_text, word_timings

_SPACE = re.compile(r"\s+")


def squeeze(text: str) -> str:
    """공백을 뺀 글자열. 정렬은 공백 처리를 바꿀 수 있어도 글자는 못 바꿉니다."""
    return _SPACE.sub("", text)


def diagnose(audio: Path, script: str, starts: list[float], *, model: str, language: str) -> None:
    """설정을 바꿔 가며 첫 자막 시작이 어떻게 달라지는지 비교합니다.

    판정에는 쓰지 않습니다. 어느 설정이 시각을 앞당기는지 보기 위한 것입니다.
    모델은 한 번만 불러와 재사용합니다.
    """
    try:
        import stable_whisper
    except ImportError:
        print("\nstable-ts가 없어 설정 비교를 건너뜁니다.")
        return
    engine = stable_whisper.load_faster_whisper(model, device="cpu", compute_type="int8")

    # 줄 묶기가 왜 포기했는지 보려면 단어 시각이 어떻게 나왔는지 봐야 합니다.
    plain = engine.align(str(audio), script, language=language)
    words = word_timings(plain)
    lines = [line for line in script.splitlines() if line.strip()]
    print(f"\n단어 시각 {len(words)}개, 대본 줄 {len(lines)}개")
    joined = squeeze("".join(w.text for w in words))
    print(f"  대본 글자 {len(squeeze(script))}자, 단어 글자 {len(joined)}자")
    print("  앞 단어: " + " | ".join(repr(w.text) for w in words[:8]))
    mapped = cues_for_lines(script.splitlines(), words)
    print(f"  줄 묶기 결과: {'자막 ' + str(len(mapped)) + '개' if mapped else '포기(None)'}")

    variants = [
        ("정렬기 줄 유지 옵션", script, {"original_split": True}),
        ("줄 유지 + 무음 보정 끔", script, {"original_split": True, "suppress_silence": False}),
        ("줄 유지 + VAD", script, {"original_split": True, "vad": True}),
        ("한 줄 대본", script.replace("\n", " "), {}),
    ]
    print(f"\n{'설정':<24} {'자막 수':>7} {'첫 시작':>9} {'첫 오차':>9} {'최대 오차':>10}")
    for label, text, options in variants:
        try:
            result = engine.align(str(audio), text, language=language, **options)
        except TypeError as exc:  # 이 버전에 없는 옵션
            print(f"{label:<24} 지원하지 않는 옵션: {exc}")
            continue
        except Exception as exc:  # noqa: BLE001 - 비교는 실패해도 판정을 막지 않습니다.
            print(f"{label:<24} 실행 실패: {type(exc).__name__}")
            continue
        found = [s for s in result.segments if s.text.strip() and s.end > s.start]
        if not found:
            print(f"{label:<24} 결과 없음")
            continue
        first = found[0].start
        worst = max(min(abs(t - s.start) for t in starts) for s in found)
        print(
            f"{label:<24} {len(found):>7} {first:>8.2f}초 "
            f"{abs(first - starts[0]):>8.2f}초 {worst:>9.2f}초"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--model", default="tiny")
    parser.add_argument("--language", default="ko")
    parser.add_argument("--tolerance", type=float, default=1.0)
    parser.add_argument("--no-diagnose", action="store_true", help="설정별 비교를 건너뜁니다.")
    args = parser.parse_args()

    expected = json.loads((args.directory / "expected.json").read_text(encoding="utf-8"))
    sentences = expected["sentences"]
    # 한 줄에 한 문장. 줄바꿈이 자막 경계가 됩니다.
    script = "\n".join(item["text"] for item in sentences)
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

    # 자막 시작마다 가장 가까운 실제 문장 시작과의 거리를 잽니다. 자막 수가
    # 문장 수와 달라도(정렬기가 합치거나 더 나눠도) 비교할 수 있습니다.
    starts = [item["start"] for item in sentences]
    print(f"\n{'자막':>4} {'정렬 시작':>10} {'가장 가까운 실제':>16} {'오차':>8}")
    worst = 0.0
    matched: set[float] = set()
    for index, cue in enumerate(cues, start=1):
        nearest = min(starts, key=lambda s: abs(s - cue.start))
        gap = abs(nearest - cue.start)
        worst = max(worst, gap)
        if gap <= args.tolerance:
            matched.add(nearest)
        print(f"{index:>4} {cue.start:>9.2f}초 {nearest:>15.2f}초 {gap:>7.2f}초")

    print(f"\n자막 시작 시각 최대 오차 {worst:.2f}초 (한계 {args.tolerance:.1f}초)")
    print(f"문장 경계 {len(matched)}/{len(sentences)}개를 자막 경계로 찾았습니다.")
    if worst > args.tolerance:
        problems.append(f"자막 시작 오차 {worst:.2f}초가 한계를 넘습니다.")
    if len(matched) < len(sentences):
        missing = [f"{s:.2f}초" for s in starts if s not in matched]
        problems.append(
            "문장 경계를 자막 경계로 남기지 못했습니다: " + ", ".join(missing) + ". "
            "줄바꿈이 있는 대본인데도 합쳐졌다면 단어 시각 묶기가 포기한 것입니다."
        )

    if not args.no_diagnose:
        diagnose(audio, script, starts, model=args.model, language=args.language)

    if problems:
        print("\n문제:")
        for problem in problems:
            print(f"- {problem}")
        return 1
    print("\n정렬이 글자를 지키고 문장 시각을 한계 안에서 맞췄습니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
