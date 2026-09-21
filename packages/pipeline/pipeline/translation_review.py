"""어색한 번역 고르기. 기계 번역 결과에서 **다시 볼 만한 자막**만 추립니다.

번역 전체를 LLM에 다시 맡기면 값이 몇 배로 뜁니다. 대부분의 문장은 기계
번역으로 충분하고, 문제는 몇 군데에 몰립니다. 그 몇 군데만 고르는 것이 이
모듈의 일입니다. **외부 호출 없이, 원문과 번역문만 보고 판정합니다.**

## 무엇을 보는가

| 신호 | 왜 |
|---|---|
| 원문 그대로 | 번역기가 손대지 못한 문장입니다. |
| 비어 있음 | 내용이 통째로 사라졌습니다. |
| 길이 이상 | 같은 묶음의 **보통 비율**의 절반 이하이거나 두 배 이상. 빠뜨렸거나 늘어놓았습니다. |
| 같은 말 반복 | 기계 번역이 무너질 때 나오는 전형적인 모양입니다. |
| 용어 누락 | 넣기로 한 표기가 번역문에 없습니다. |
| 문장 조각 | 문장부호로 끝나지 않는 조각은 문맥 없이 번역된 것입니다. |

길이 기준은 **이 묶음 자체의 중앙값**에서 잡습니다. 언어쌍마다 늘어나는
비율이 달라(한국어 → 영어는 1.2~1.7배) 고정값을 두면 한쪽 언어에서만
맞습니다. 표본이 너무 적으면(4개 미만) 넉넉한 고정 범위를 씁니다.

## 아는 한계

- 여기서 걸리지 않는 어색함이 훨씬 많습니다. **뜻이 틀렸는지는 보지
  않습니다.** 원문과 번역문의 겉모양만 봅니다.
- 걸린 것이 반드시 틀린 것도 아닙니다. 짧은 감탄사는 길이 비율이 크게
  흔들립니다. 그래서 점수를 매겨 **상위 일부만** 고릅니다.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from statistics import median

from pipeline.subtitles import text_width
from pipeline.translation_context import ends_sentence

# 이 점수 아래는 고르지 않습니다.
THRESHOLD = 0.5
# 한 묶음에서 다시 볼 자막의 최대 비율. 비용과 예산 계산의 상한이기도 합니다.
MAX_SHARE = 0.3
MAX_COUNT = 20
# 중앙값을 믿을 만큼의 표본.
ENOUGH = 4
# 표본이 적을 때 쓰는 넉넉한 범위.
LOOSE = (0.4, 2.5)

_WORD = re.compile(r"\w+", re.UNICODE)
_RUN = re.compile(r"(.)\1{3,}")


@dataclass
class Finding:
    """다시 볼 자막 하나. `score`가 클수록 의심스럽습니다."""

    index: int
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)

    def note(self, score: float, reason: str) -> None:
        self.score += score
        self.reasons.append(reason)


def _ratios(pairs: Sequence[tuple[str, str]]) -> list[float | None]:
    """번역문이 원문보다 몇 배 넓어졌는지. 원문이 비면 `None`입니다."""
    found: list[float | None] = []
    for source, translated in pairs:
        width = text_width(source)
        found.append(text_width(translated) / width if width > 0 else None)
    return found


def _band(ratios: Sequence[float | None]) -> tuple[float, float]:
    """정상으로 볼 길이 비율의 범위. 이 묶음의 중앙값에서 잡습니다."""
    usable = [ratio for ratio in ratios if ratio is not None and ratio > 0]
    if len(usable) < ENOUGH:
        return LOOSE
    middle = median(usable)
    return middle / 2, middle * 2


def _repeats(text: str) -> bool:
    """같은 말이 잇따라 반복되는지. 기계 번역이 무너진 모양입니다."""
    if _RUN.search(text):
        return True
    words = [word.casefold() for word in _WORD.findall(text)]
    return any(words[at] == words[at + 1] == words[at + 2] for at in range(len(words) - 2))


def review(
    pairs: Sequence[tuple[str, str]],
    *,
    missing_terms: Mapping[int, Sequence[str]] | None = None,
    grouped: Sequence[int] = (),
) -> list[Finding]:
    """원문·번역문 쌍을 보고 의심스러운 자막을 점수와 함께 돌려줍니다.

    `missing_terms`는 자리 번호마다 번역문에서 사라진 용어, `grouped`는 문맥
    배치로 **묶여서** 번역된 자리입니다. 묶인 자리는 조각이어도 문맥을 받고
    번역된 것이므로 조각이라는 이유로 의심하지 않습니다.
    """
    ratios = _ratios(pairs)
    low, high = _band(ratios)
    inside = set(grouped)
    findings: list[Finding] = []
    for index, (source, translated) in enumerate(pairs):
        finding = Finding(index=index)
        stripped, output = source.strip(), translated.strip()
        if stripped and not output:
            finding.note(1.0, "번역문이 비어 있습니다.")
        elif stripped and stripped == output and _WORD.search(stripped):
            finding.note(1.0, "원문이 그대로 남았습니다.")
        ratio = ratios[index]
        if ratio is not None and output:
            if ratio < low:
                finding.note(0.7, f"번역문이 너무 짧습니다(길이 비율 {ratio:.2f}).")
            elif ratio > high:
                finding.note(0.7, f"번역문이 너무 깁니다(길이 비율 {ratio:.2f}).")
        if output and _repeats(output):
            finding.note(0.8, "같은 말이 잇따라 반복됩니다.")
        gone = list((missing_terms or {}).get(index, ()))
        if gone:
            finding.note(0.9, f"용어가 빠졌습니다: {', '.join(gone)}")
        if stripped and not ends_sentence(stripped) and index not in inside:
            finding.note(0.4, "문장 조각을 문맥 없이 번역했습니다.")
        if finding.score >= THRESHOLD:
            findings.append(finding)
    findings.sort(key=lambda item: (-item.score, item.index))
    return findings


def review_limit(count: int) -> int:
    """한 묶음에서 다시 볼 수 있는 최대 자막 수.

    비용이 번역량에 비례해 늘지 않도록 상한을 둡니다. 예산 계산도 이 수를
    씁니다(`paid_estimate`).
    """
    if count <= 0:
        return 0
    return max(1, min(MAX_COUNT, int(count * MAX_SHARE)))


def pick(findings: Sequence[Finding], count: int) -> list[int]:
    """실제로 다시 번역할 자리. 점수 높은 것부터 상한까지입니다."""
    return sorted(finding.index for finding in findings[: review_limit(count)])
