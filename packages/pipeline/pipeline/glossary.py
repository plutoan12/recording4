"""용어집 보호. 번역기에 보내기 전에 지킬 말을 자리표시자로 바꾸고, 받은 뒤 되돌립니다.

K-pop 콘텐츠의 인명·그룹명·곡명·브랜드명은 번역기가 뜻으로 옮기거나 표기를
바꿉니다. 용어집 항목(원문 → 목표 표기, 비어 있으면 그대로)은 `⟦n⟧`로 바꿔
보내고 답에서 그 자리에 목표 표기를 넣습니다. 숫자는 자리표시자로 바꾸면
번역기가 수량 문맥을 잃으므로, **원문에 없는 다른 숫자**로 바꿨다가 되돌립니다.

번역기가 자리표시자를 지우면 되돌릴 수 없습니다. 그 문장 번호를 함께 돌려주니
호출한 쪽이 기록합니다. 조용히 넘기지 않습니다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

TERM = "⟦{}⟧"
_TERM_PATTERN = re.compile(r"⟦(\d+)⟧")
# 1,000 · 3.5 · 2018 · 7 같은 숫자 토큰. 시각(12:30)은 콜론으로 갈라져 둘로 잡힙니다.
_NUMBER = re.compile(r"\d[\d,.]*\d|\d")
_LATIN = re.compile(r"^[A-Za-z0-9 .'&-]+$")
# 네 자리 숫자는 천 단위 구분자가 붙지 않아 번역기가 모양을 바꾸지 않습니다.
_SENTINEL_FIRST, _SENTINEL_LAST = 9001, 9999


@dataclass
class Protected:
    texts: list[str]
    # 문장마다 자리표시자 → 되돌릴 문자열.
    slots: list[dict[str, str]] = field(default_factory=list)


def _term_pattern(term: str) -> re.Pattern[str]:
    if _LATIN.match(term):
        # 라틴 문자 용어는 단어 경계 안에서만. 'IU'가 'IUS'에 걸리지 않게 합니다.
        return re.compile(rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])")
    return re.compile(re.escape(term))


def _protect_one(
    text: str, patterns: list[tuple[re.Pattern[str], str]], numbers: bool
) -> tuple[str, dict[str, str]]:
    slots: dict[str, str] = {}

    def swap_term(match: re.Match[str], replacement: str) -> str:
        key = TERM.format(len(slots))
        slots[key] = replacement
        return key

    for pattern, replacement in patterns:
        text = pattern.sub(lambda m, r=replacement: swap_term(m, r), text)
    if not numbers:
        return text, slots
    taken = set(_NUMBER.findall(text))
    sentinel = _SENTINEL_FIRST

    def swap_number(match: re.Match[str]) -> str:
        nonlocal sentinel
        # 자리표시자 안의 숫자(⟦0⟧)는 건드리지 않습니다.
        if _TERM_PATTERN.fullmatch(text[max(0, match.start() - 1) : match.end() + 1]):
            return match.group(0)
        while str(sentinel) in taken and sentinel < _SENTINEL_LAST:
            sentinel += 1
        if sentinel > _SENTINEL_LAST:
            return match.group(0)
        key = str(sentinel)
        sentinel += 1
        slots[key] = match.group(0)
        return key

    return _NUMBER.sub(swap_number, text), slots


def protect(texts: list[str], entries: dict[str, str | None], *, numbers: bool = True) -> Protected:
    """용어와 숫자를 자리표시자로 바꿉니다. 긴 용어부터 잡아 짧은 용어가 안을 가르지 않게 합니다."""
    patterns = [
        (_term_pattern(term), (target or term))
        for term, target in sorted(entries.items(), key=lambda item: -len(item[0]))
        if term
    ]
    protected = Protected(texts=[])
    for text in texts:
        replaced, slots = _protect_one(text, patterns, numbers)
        protected.texts.append(replaced)
        protected.slots.append(slots)
    return protected


def restore(translated: list[str], protected: Protected) -> tuple[list[str], list[int]]:
    """자리표시자를 되돌립니다. (문장들, 자리표시자가 사라진 문장 번호) 순입니다."""
    if len(translated) != len(protected.slots):
        raise ValueError("번역 문장 수가 보호한 문장 수와 다릅니다.")
    output, lost = [], []
    for index, (text, slots) in enumerate(zip(translated, protected.slots, strict=True)):
        for key, value in sorted(slots.items(), key=lambda item: -len(item[0])):
            if key not in text:
                lost.append(index)
                continue
            text = text.replace(key, value)
        output.append(text)
    return output, sorted(set(lost))


# ---------------------------------------------------------------------------
# 프롬프트를 쓰는 번역기(LLM)용. 자리표시자 대신 용어를 지시로 주고, 답을 검사합니다.
# rockbenben/subtitle-translator(src/app/lib/translation/glossary.ts, MIT)의
# filterTermsMatchingText · findGlossaryViolations · applyGlossaryToText를 옮겼습니다.
# THIRD_PARTY_NOTICES.md에 원 저작권 고지를 둡니다.
# ---------------------------------------------------------------------------


def terms_in_text(entries: dict[str, str | None], text: str) -> dict[str, str]:
    """이 문장에 실제로 나오는 용어만. 500개짜리 용어집을 두 줄 묶음마다 보내지 않습니다."""
    return {
        term: (target or term)
        for term, target in entries.items()
        if term and _term_pattern(term).search(text)
    }


def violations(source: str, translated: str, entries: dict[str, str | None]) -> dict[str, str]:
    """원문에 있는 용어인데 번역에 목표 표기가 없는 것. 대소문자는 가리지 않습니다."""
    haystack = translated.casefold()
    return {
        term: target
        for term, target in terms_in_text(entries, source).items()
        if target.casefold() not in haystack
    }


def missing_numbers(source: str, translated: str) -> list[str]:
    """원문의 숫자 중 번역에 그대로 없는 것. 숫자는 뜻으로 옮길 것이 없습니다."""
    return [n for n in _NUMBER.findall(source) if n not in translated]


def _replace_safe(term: str, target: str) -> bool:
    # 목표 표기 안에 원문 용어가 다시 나오면 치환이 겹쳐 붙습니다("AI"→"AI助手").
    return term.casefold() == target.casefold() or not _term_pattern(term).search(target)


def apply_terms(translated: str, terms: dict[str, str]) -> str:
    """번역에 남은 원문 용어를 목표 표기로 바꿉니다(새어 나온 것 잡기). 긴 용어부터."""
    for term, target in sorted(terms.items(), key=lambda item: -len(item[0])):
        if term and _replace_safe(term, target):
            translated = _term_pattern(term).sub(target, translated)
    return translated


def prompt_block(terms: dict[str, str], *, strict: bool = False) -> str:
    if not terms:
        return ""
    lines = "\n".join(f"{term} → {target}" for term, target in terms.items())
    if strict:
        return (
            "STRICT GLOSSARY — the previous translation failed to apply these required terms. "
            "Every occurrence of each source term below MUST appear in the translation exactly "
            "as its specified target (source → target):\n" + lines
        )
    return (
        "Glossary — always translate these terms exactly as specified (source → target). "
        "Keep them consistent everywhere they appear:\n" + lines
    )
