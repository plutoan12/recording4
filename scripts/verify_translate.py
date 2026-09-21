#!/usr/bin/env python3
"""한국어 → 영어 번역 품질을 재고, 그 결과가 자막 규칙에 맞는지 봅니다.

번역은 지금까지 "호출이 성공했다"까지만 확인했습니다. 무엇을 내놓는지는 잰
적이 없습니다. 이 스크립트는 사람이 만든 번역(참조)과 비교해 수치를 내고,
그 번역문이 **원문이 차지한 시간 안에서** 목표 언어 자막 규칙에 들어가는지도
함께 봅니다. 번역이 맞아도 자막으로 안 들어가면 화면에서는 깨집니다.

**유료 호출입니다.** Google Cloud Translation은 100만 자당 20 USD입니다.
아래 표본(몇백 자)은 1센트가 안 되지만, `--allow-paid` 없이는 부르지
않습니다. 자격증명이 있는 컴퓨터에서 실행하세요.

    python3 scripts/verify_translate.py --pairs docs/samples/ko-en.json --allow-paid

`--allow-paid` 없이 돌리면 사람이 만든 참조 번역을 대신 넣어 봅니다(무료).
번역기가 없어도 "영어 자막이 원문의 시간 안에 들어가는가"는 확인할 수
있습니다. CI가 이 형태로 돕니다.

판정 기준:

- 번역 결과의 문장 수가 입력과 같을 것. 다르면 자막과 짝이 맞지 않습니다.
- 문자 F 점수(chrF)가 한계 아래로 떨어지지 않을 것. 한계는 품질 목표가
  아니라 회귀 감시용입니다. 표본이 작아 값은 흔들립니다.
- 규칙을 거친 자막이 줄 수·겹침을 어기지 않을 것.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pipeline.editing import Cue
from pipeline.glossary import Glossary, protect
from pipeline.subtitles import apply_rules, check, normalize, rules_for, text_width


def grams(text: str, size: int) -> list[str]:
    squeezed = normalize(text).replace(" ", "")
    return [squeezed[i : i + size] for i in range(len(squeezed) - size + 1)]


def chrf(reference: str, candidate: str, *, order: int = 6, beta: float = 2.0) -> float:
    """문자 n그램 F 점수(chrF). 0~1이고 높을수록 참조와 비슷합니다.

    단어 단위 점수(BLEU)는 어순이 자유로운 짧은 문장에서 심하게 흔들립니다.
    문자 단위는 어미 변화와 띄어쓰기 차이에 덜 민감해서 표본이 작을 때
    그나마 읽을 만합니다. 그래도 **수치 하나로 번역 품질을 말할 수는
    없습니다.** 문장별 원문·번역을 항상 함께 출력하는 이유입니다.
    """
    scores: list[float] = []
    for size in range(1, order + 1):
        left, right = grams(reference, size), grams(candidate, size)
        if not left or not right:
            continue
        shared = 0
        pool = list(right)
        for gram in left:
            if gram in pool:
                pool.remove(gram)
                shared += 1
        precision = shared / len(right)
        recall = shared / len(left)
        if precision + recall:
            weight = beta * beta
            scores.append((1 + weight) * precision * recall / (weight * precision + recall))
        else:
            scores.append(0.0)
    return sum(scores) / len(scores) if scores else 0.0


def spans(sources: list[str], language: str) -> list[float]:
    """원문 한 문장이 화면에 머무는 시간. 그 언어의 읽기 속도로 잡습니다.

    실제 시각은 원본 음성 정렬이 정합니다. 여기에는 음성이 없으므로 원문을
    읽는 데 걸리는 시간을 대신 씁니다. 말하는 속도와 읽는 속도는 다르지만,
    **번역문이 쓸 수 있는 시간은 원문이 차지한 시간뿐**이라는 관계는 같습니다.
    """
    rules = rules_for(language)
    return [
        max(rules.min_duration, text_width(normalize(text)) / rules.max_cps) for text in sources
    ]


def fits_rules(
    texts: list[str], language: str, windows: list[float]
) -> tuple[list[str], list[str]]:
    """번역문을 원문이 쓰던 시간 안에 자막으로 넣어 봅니다. (보고, 문제) 순입니다.

    시간을 원문에서 가져오는 것이 이 검사의 요점입니다. 번역문 자기 길이로
    시간을 주면 아무리 길어져도 항상 들어가서 검사가 아무것도 못 잡습니다.
    영어는 한국어보다 폭이 커지는데(이 표본에서 1.2~1.7배), 시간은 원본
    음성이 정하므로 늘어난 글자를 같은 시간에 넣어야 합니다. 못 넣으면
    화면에서 줄이 넘칩니다.
    """
    rules = rules_for(language)
    cues: list[Cue] = []
    cursor = 0.0
    for text, window in zip(texts, windows, strict=False):
        cues.append(Cue(start=cursor, end=cursor + window, text=text))
        cursor += window + 1.0  # 붙은 자막을 겹침으로 세지 않도록 띄웁니다.
    shaped = apply_rules(cues, rules)
    report = [
        f"  {c.text.replace(chr(10), ' / ')}  (폭 {text_width(c.text.replace(chr(10), ' ')):.1f})"
        for c in shaped
    ]
    problems = [
        f"자막 {v.index + 1}: {v.detail}"
        for v in check(shaped, rules)
        if v.kind in ("lines", "overlap")
    ]
    return report, problems


def translate(
    texts: list[str], target: str, source: str, project: str, glossary: Glossary | None = None
) -> tuple[list[str], list[str]]:
    """실제 Google 번역. 유료 호출입니다. (번역문, 빠진 용어) 순입니다."""
    from worker.providers import GoogleTranslator

    translator = GoogleTranslator(project, allow_paid=True)
    output = translator.translate(texts, target, source, glossary=glossary)
    return output, [term for terms in translator.missing_terms.values() for term in terms]


def load_glossary(path: Path | None, source: str, target: str) -> Glossary | None:
    """용어집 파일. `{"entries": {"원문": "번역 표기"}}` 형식이면 됩니다."""
    if path is None:
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    entries = data.get("entries", data) if isinstance(data, dict) else data
    return Glossary(source_language=source, target_language=target, entries=entries)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pairs", type=Path, default=None, help="원문·참조 번역 묶음 JSON")
    parser.add_argument("--source", default="ko")
    parser.add_argument("--target", default="en")
    parser.add_argument("--project", default=None, help="Google Cloud 프로젝트")
    parser.add_argument("--allow-paid", action="store_true", help="실제 번역 호출을 허용합니다.")
    parser.add_argument("--glossary", type=Path, default=None, help="용어집 JSON")
    # 품질 목표가 아니라 회귀 감시용 하한입니다. 표본이 작아 흔들립니다.
    parser.add_argument("--min-chrf", type=float, default=0.40)
    args = parser.parse_args()

    if not args.pairs:
        print("원문·참조 묶음이 없습니다. --pairs로 주세요.")
        return 2
    pairs = json.loads(args.pairs.read_text(encoding="utf-8"))
    sources = [item["source"] for item in pairs]
    references = [item["reference"] for item in pairs]

    problems: list[str] = []
    glossary = load_glossary(args.glossary, args.source, args.target)
    if glossary is not None:
        # 용어가 어디에 걸리는지는 번역 없이도 봅니다(무료).
        wanted = [term for text in sources for term in protect(text, glossary)[1]]
        print(
            f"용어집 {len(glossary.entries)}개, 이 표본에서 걸리는 자리 {len(wanted)}곳: {wanted}\n"
        )
        if not wanted:
            problems.append("표본에 용어집이 걸리는 자리가 없습니다. 표본이나 용어를 확인하세요.")

    if not args.allow_paid:
        print("유료 호출을 하지 않습니다(--allow-paid 없음). 참조 번역만 규칙에 넣어 봅니다.\n")
        report, found = fits_rules(references, args.target, spans(sources, args.source))
        print(f"참조 번역을 {args.target} 자막 규칙에 넣은 결과:")
        print("\n".join(report))
        problems += found
    else:
        if not args.project:
            print("--project가 필요합니다(Google Cloud 프로젝트).")
            return 2
        print(f"실제 번역 호출: {len(sources)}문장, {sum(map(len, sources))}자\n")
        candidates, gone = translate(sources, args.target, args.source, args.project, glossary)
        if glossary is not None:
            landed = [term for text in sources for term in protect(text, glossary)[1]]
            print(f"용어 {len(landed) - len(gone)}/{len(landed)}곳이 번역문에 남았습니다.")
            if gone:
                print(f"  빠진 용어: {gone}")
                problems.append(f"번역문에서 용어 {len(gone)}곳이 사라졌습니다: {gone}")
            print()
        if len(candidates) != len(sources):
            problems.append(f"번역 문장 수가 다릅니다: 입력 {len(sources)}, 결과 {len(candidates)}")

        total = 0.0
        for index, (source, reference, candidate) in enumerate(
            zip(sources, references, candidates, strict=False), start=1
        ):
            score = chrf(reference, candidate)
            total += score
            print(f"  {index}. chrF {score:.2f}")
            print(f"     원문: {source}")
            print(f"     참조: {reference}")
            print(f"     번역: {candidate}")
        average = total / len(candidates) if candidates else 0.0
        print(f"\n평균 chrF {average:.2f} (하한 {args.min_chrf:.2f})")
        if average < args.min_chrf:
            problems.append(f"평균 chrF {average:.2f}가 하한 {args.min_chrf:.2f}보다 낮습니다.")

        report, found = fits_rules(candidates, args.target, spans(sources, args.source))
        print(f"\n번역문을 {args.target} 자막 규칙에 넣은 결과:")
        print("\n".join(report))
        problems += found

    if problems:
        print("\n문제:")
        for problem in problems:
            print(f"- {problem}")
        return 1
    print("\n수치보다 위의 문장별 비교를 먼저 보세요. 수치 하나로 번역 품질을 말할 수 없습니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
