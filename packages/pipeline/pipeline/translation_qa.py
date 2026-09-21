"""번역 QA. 문제를 **보고만** 하고 고치지 않습니다. 고치는 것은 사람 또는 보정 단계입니다.

검사 항목(자막 번호마다):
- glossary: 원문에 용어가 있는데 번역에 목표 표기가 없음
- number: 원문 숫자가 번역에 그대로 없음
- untranslated: 번역이 원문과 같음(출발·목표 언어가 다른데)
- empty: 번역이 비어 있음
- script: 출발 언어 글자(한글·가나·태국 문자·데바나가리)가 번역에 남음
- lines / cps / duration: 목표 언어 자막 규칙(pipeline.subtitles.check)에 안 들어감.
  시간은 원문이 차지한 시간입니다. 번역이 길어져도 시간은 늘지 않습니다.

구조는 llm-subs의 review/checks(구조만)와 LLM-Subtrans의 SubtitleValidator를 따랐습니다.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import asdict, dataclass

from pipeline.editing import Cue
from pipeline.glossary import missing_numbers, violations
from pipeline.languages import normalize as normalize_code
from pipeline.subtitles import DEFAULT_RULES, SubtitleRules, check, normalize, rules_for

# 출발 언어에 고유한 글자. 목표 언어가 이 글자를 쓰지 않으면 남아 있을 이유가 없습니다.
SCRIPTS: dict[str, re.Pattern[str]] = {
    "ko": re.compile(r"[가-힣ㄱ-ㆎ]"),
    "ja": re.compile(r"[぀-ゟ゠-ヿ]"),
    "th": re.compile(r"[฀-๿]"),
    "hi": re.compile(r"[ऀ-ॿ]"),
}


@dataclass(frozen=True)
class Issue:
    index: int
    kind: str
    detail: str


def _without_terms(text: str, entries: dict[str, str | None]) -> str:
    """용어집이 정한 목표 표기는 출발 언어 글자여도 문제가 아닙니다."""
    for term, target in entries.items():
        text = text.replace(target or term, "")
    return text


def review(
    sources: Sequence[str],
    translations: Sequence[str],
    *,
    source: str | None,
    target: str,
    entries: dict[str, str | None] | None = None,
    timings: Sequence[tuple[float, float]] | None = None,
    rules: SubtitleRules | None = None,
) -> list[Issue]:
    if len(sources) != len(translations):
        raise ValueError("원문과 번역의 문장 수가 다릅니다.")
    entries = entries or {}
    same_language = source is not None and normalize_code(source) == normalize_code(target)
    leak = SCRIPTS.get(normalize_code(source)) if source else None
    if leak and normalize_code(source) == normalize_code(target):
        leak = None
    issues: list[Issue] = []
    for index, (original, translated) in enumerate(zip(sources, translations, strict=True)):
        if not translated.strip():
            issues.append(Issue(index, "empty", "번역이 비어 있습니다."))
            continue
        wrong = violations(original, translated, entries)
        if wrong:
            issues.append(
                Issue(
                    index, "glossary", "용어집: " + ", ".join(f"{k}→{v}" for k, v in wrong.items())
                )
            )
        numbers = missing_numbers(original, translated)
        if numbers:
            issues.append(Issue(index, "number", "숫자 누락: " + ", ".join(numbers)))
        if not same_language and normalize(original) == normalize(translated):
            issues.append(Issue(index, "untranslated", "원문과 같습니다."))
        elif leak and leak.search(_without_terms(translated, entries)):
            issues.append(Issue(index, "script", f"{source} 글자가 번역에 남아 있습니다."))
    if timings is not None:
        cues = [
            Cue(start=start, end=max(end, start + 0.001), text=text or " ")
            for (start, end), text in zip(timings, translations, strict=True)
        ]
        for found in check(cues, rules or rules_for(target, DEFAULT_RULES)):
            if found.kind in ("lines", "cps"):
                issues.append(Issue(found.index, found.kind, found.detail))
    return sorted(issues, key=lambda i: (i.index, i.kind))


def grouped(issues: Sequence[Issue]) -> list[dict]:
    """작업 데이터·화면에 저장하는 모양: [{index, issues: [detail, ...]}]."""
    rows: dict[int, list[str]] = {}
    for issue in issues:
        rows.setdefault(issue.index, []).append(issue.detail)
    return [{"index": index, "issues": details} for index, details in sorted(rows.items())]


def as_dicts(issues: Sequence[Issue]) -> list[dict]:
    return [asdict(issue) for issue in issues]
