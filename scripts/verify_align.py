#!/usr/bin/env python3
"""stable-ts 정렬을 실제 음성에 돌려 보고 시각이 맞는지 잽니다.

make_speech_sample.py가 만든 음성은 문장 시작 시각을 우리가 알고 있습니다.
같은 대본을 타이밍 없이 넣고 정렬한 뒤, 나온 시각을 아는 값과 비교합니다.
모델을 실제로 내려받아 돌리므로 CI에서 필요할 때만 실행합니다.

    python scripts/verify_align.py --directory /audio --model small

대본은 한 줄에 한 문장씩 넣습니다. 정렬은 한 덩어리로 돌리고 줄 나누기는
단어 시각으로 우리가 하므로, 문장별 시각을 곧바로 비교할 수 있습니다.

판정 기준:

- 글자가 하나도 바뀌지 않을 것. 정렬은 전사가 아닙니다.
- 자막이 시간순이고 서로 겹치지 않을 것.
- 자막마다 시작 시각 오차가 한계(기본 1초) 안일 것. 실제 오차는 항상 출력합니다.
- 문장 경계가 자막 경계로 남을 것. 여러 문장이 한 자막으로 합쳐지면 보고합니다.
- 자막이 다음 문장 발화를 침범하지 않을 것. 끝이 밀리면 다음 말이 시작된 뒤에도
  앞 자막이 남습니다.
- 표시 규칙(`apply_rules`)을 거친 뒤에도 줄 수와 겹침이 규칙 안일 것.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from pipeline.alignment import cues_for_lines, merge_spans
from pipeline.editing import Cue
from pipeline.subtitles import DEFAULT_RULES, apply_rules, check, normalize, text_width
from worker.analysis import align_text, silence_spans, vad_spans, word_timings

_SPACE = re.compile(r"\s+")


def squeeze(text: str) -> str:
    """공백을 뺀 글자열. 정렬은 공백 처리를 바꿀 수 있어도 글자는 못 바꿉니다."""
    return _SPACE.sub("", text)


def show(label: str, spans: list[tuple[float, float]]) -> None:
    shown = ", ".join(f"{b:.2f}~{e:.2f}" for b, e in spans[:8])
    print(f"  {label} {len(spans)}개: {shown}{' ...' if len(spans) > 8 else ''}")


def report_spans(audio: Path) -> None:
    """자막 시작을 맞추는 근거를 그대로 보여 줍니다.

    어느 공급자가 무엇을 줬는지, 합치기 전과 후가 어떻게 다른지 다 찍습니다.
    한 줄만 찍었을 때 합치기가 다 뭉갠 것인지 VAD가 안 끊은 것인지 구분할 수
    없어서 한 번 더 재야 했습니다(측정: 18초 전체가 구간 1개).
    """
    spans = vad_spans(audio)
    show("VAD 원본", spans)
    if not spans:
        spans = silence_spans(audio)
        show("무음 감지(대안)", spans)
    show("합친 뒤", merge_spans(spans))


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


def report_ends(cues: list[Cue], sentences: list[dict]) -> list[str]:
    """자막 끝 시각을 잽니다. 시작만 재면 자막이 언제 사라지는지 아무도 모릅니다.

    끝의 정답은 시작만큼 또렷하지 않습니다. 사람 녹음은 말끝에 숨소리와 잔향이
    남아, 같은 문턱으로 잰 끝이 실제 말끝보다 늦습니다(측정: 자막 1의 정답 끝
    11.93초, VAD가 본 발화 끝 10.46초). 그래서 정답과의 차이는 찍기만 하고,
    판정은 자막이 지켜야 할 것으로 합니다: 다음 문장이 시작된 뒤까지 앞 자막이
    남아 있으면 안 됩니다.
    """
    problems: list[str] = []
    ends = [item["end"] for item in sentences]
    print(f"\n{'자막':>4} {'정렬 끝':>10} {'가장 가까운 실제':>16} {'차이':>8} {'표시 시간':>10}")
    for index, cue in enumerate(cues, start=1):
        nearest = min(ends, key=lambda value: abs(value - cue.end))
        print(
            f"{index:>4} {cue.end:>9.2f}초 {nearest:>15.2f}초 "
            f"{abs(nearest - cue.end):>7.2f}초 {cue.end - cue.start:>9.2f}초"
        )
    for cue in cues:
        # 이 자막이 맡은 문장. 자막 시작에 가장 가까운 문장입니다. 자막 시작이
        # 정답보다 조금 이르면(맞게 맞춘 경우에도 0.01초 정도) 자기 문장이
        # "다음 문장"으로 잡힙니다. 그래서 순서가 아니라 가까움으로 고릅니다.
        own = min(sentences, key=lambda item: abs(item["start"] - cue.start))
        for item in sentences:
            if item["start"] <= own["start"] + 0.001 or cue.end <= item["start"] + 0.001:
                continue
            # 한 자막이 두 문장을 담고 있으면 그 문장까지 걸치는 게 맞습니다.
            # 합쳐진 것 자체는 시작 시각 검사가 따로 잡습니다.
            if squeeze(item["text"]) in squeeze(cue.text):
                continue
            problems.append(
                f"자막이 다음 문장 발화를 침범합니다: {cue.start:.2f}~{cue.end:.2f}초 자막이 "
                f"{item['start']:.2f}초에 시작하는 문장까지 남습니다."
            )
            break
        if problems:
            break
    return problems


def report_rules(cues: list[Cue]) -> list[str]:
    """표시 규칙을 거친 뒤의 자막을 봅니다. 화면에 뜨는 것은 이쪽입니다.

    정렬 결과는 그대로 화면에 가지 않습니다. `apply_rules`가 줄을 나누고 긴
    자막을 쪼갠 뒤에야 렌더됩니다. 정렬 시각이 맞아도 그 뒤에서 깨지면 본
    사람에게는 똑같이 깨진 자막입니다.

    읽기 속도(CPS)와 너무 긴 표시 시간은 보고만 합니다. CPS는 나눈다고 줄지
    않고(같은 글자를 같은 시간에 읽습니다) 말이 빠른 대본의 성질이지 정렬의
    결함이 아닙니다. 줄 수와 겹침은 규칙이 지켜져야 하므로 실패로 봅니다.
    """
    shaped = apply_rules(cues, DEFAULT_RULES)
    print(f"\n표시 규칙 적용 뒤 자막 {len(shaped)}개 (정렬 결과 {len(cues)}개)")
    for cue in shaped:
        width = text_width(normalize(cue.text.replace("\n", " ")))
        duration = cue.end - cue.start
        speed = width / duration if duration > 0 else 0.0
        shown = cue.text.replace("\n", " / ")
        print(f"  {cue.start:>6.2f} ~ {cue.end:>6.2f} ({speed:>5.1f}자/초)  {shown}")

    problems: list[str] = []
    for violation in check(shaped, DEFAULT_RULES):
        line = f"자막 {violation.index + 1}: {violation.detail}"
        if violation.kind in ("lines", "overlap"):
            problems.append(f"표시 규칙을 지키지 못했습니다. {line}")
        else:
            print(f"  보고: {line}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    # 운영 기본값(R4_WHISPER_MODEL)과 같은 모델로 재야 의미가 있습니다.
    parser.add_argument("--model", default="small")
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
    report_spans(audio)
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

    problems.extend(report_ends(cues, sentences))
    problems.extend(report_rules(cues))

    if not args.no_diagnose:
        diagnose(audio, script, starts, model=args.model, language=args.language)

    if problems:
        print("\n문제:")
        for problem in problems:
            print(f"- {problem}")
        return 1
    print(
        "\n정렬이 글자를 지키고 문장 시각을 한계 안에서 맞췄습니다. "
        "끝 시각도 다음 문장을 침범하지 않았습니다."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
