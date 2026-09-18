"""자막 가독성 규칙.

순수 계산만 둡니다. 한국어 문장 분리는 kss가 설치되어 있으면 쓰고, 없으면
구두점 기준으로 내려갑니다. 어느 경우에도 글자를 버리지 않습니다.

용량이 넘치는 자막은 여러 자막으로 나눕니다. 초당 글자수(CPS)는 나눈다고
줄어들지 않으므로(같은 글자를 같은 시간에 읽습니다) 검사로만 보고합니다.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

from pipeline.editing import Cue

_SENTENCE_END = re.compile(r"(?<=[.!?…。！？])\s+")
_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class SubtitleRules:
    """자막 표시 규칙. 기본값은 한국어 기준 제안이며 측정 후 조정합니다."""

    max_chars_per_line: int = 20
    max_lines: int = 2
    max_cps: float = 20.0
    min_duration: float = 1.0
    max_duration: float = 7.0

    @property
    def capacity(self) -> int:
        """자막 하나가 담을 수 있는 최대 글자수."""
        return self.max_chars_per_line * self.max_lines

    def __post_init__(self) -> None:
        if self.max_chars_per_line < 1 or self.max_lines < 1:
            raise ValueError("줄 길이와 줄 수는 1 이상이어야 합니다.")
        if self.max_cps <= 0 or self.min_duration <= 0 or self.max_duration <= 0:
            raise ValueError("CPS와 표시 시간은 0보다 커야 합니다.")


DEFAULT_RULES = SubtitleRules()

Kind = Literal["cps", "lines", "duration", "overlap"]


@dataclass(frozen=True, slots=True)
class Violation:
    """사람이 고쳐야 하는 자막 문제. 자동으로 글자를 줄이지 않습니다."""

    index: int
    kind: Kind
    detail: str


def normalize(text: str) -> str:
    return _WHITESPACE.sub(" ", text).strip()


@lru_cache(maxsize=1)
def _kss():  # noqa: ANN202
    try:
        import kss
    except ImportError:
        return None
    return kss


def sentences(text: str) -> list[str]:
    """문장 단위로 나눕니다. kss가 없으면 구두점 기준입니다."""
    engine = _kss()
    if engine is not None:
        try:
            found = [s.strip() for s in engine.split_sentences(text) if s.strip()]
        except Exception:  # noqa: BLE001 - 분리 실패는 규칙 적용을 막지 않습니다.
            found = []
        if found:
            return found
    return [s.strip() for s in _SENTENCE_END.split(text) if s.strip()] or [text]


def wrap_text(text: str, rules: SubtitleRules = DEFAULT_RULES) -> list[str]:
    """줄 길이에 맞춰 줄바꿈합니다. 공백이 없으면 글자 단위로 자릅니다.

    줄 수 제한은 여기서 강제하지 않습니다. 넘치면 check가 보고합니다.
    """
    limit = rules.max_chars_per_line
    lines: list[str] = []
    current = ""
    for token in normalize(text).split(" "):
        while len(token) > limit:
            if current:
                lines.append(current)
                current = ""
            lines.append(token[:limit])
            token = token[limit:]
        if not token:
            continue
        candidate = f"{current} {token}" if current else token
        if len(candidate) > limit and current:
            lines.append(current)
            current = token
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines or [""]


def split_text(text: str, parts: int) -> list[str]:
    """글자 수가 고르게 되도록 parts개로 나눕니다. 경계는 문장 → 어절 순입니다."""
    text = normalize(text)
    if parts <= 1 or not text:
        return [text]
    for tokens, joiner in ((sentences(text), " "), (text.split(" "), " ")):
        if len(tokens) >= parts:
            return _group(tokens, parts, joiner)
    size = math.ceil(len(text) / parts)
    return [text[i : i + size] for i in range(0, len(text), size)]


def _group(tokens: list[str], parts: int, joiner: str) -> list[str]:
    total = sum(len(t) for t in tokens) + len(joiner) * (len(tokens) - 1)
    target = total / parts
    groups: list[list[str]] = [[]]
    length = 0
    for index, token in enumerate(tokens):
        # 남은 토큰이 남은 그룹 수와 같아지면 무조건 새 그룹을 엽니다. 빈 그룹을 막습니다.
        must_open = len(tokens) - index < parts - len(groups) + 1
        if groups[-1] and len(groups) < parts and (length >= target or must_open):
            groups.append([])
            length = 0
        groups[-1].append(token)
        length += len(token) + len(joiner)
    return [joiner.join(g) for g in groups if g]


def apply_rules(cues: list[Cue], rules: SubtitleRules = DEFAULT_RULES) -> list[Cue]:
    """자막을 표시 규칙에 맞게 다시 만듭니다. 줄바꿈은 개행 문자로 넣습니다."""
    shaped: list[Cue] = []
    for cue in cues:
        shaped.extend(_shape(cue, rules))
    return shaped


def _shape(cue: Cue, rules: SubtitleRules) -> list[Cue]:
    text = normalize(cue.text)
    duration = cue.end - cue.start
    # 나눌 수 있는 최대 조각 수. 읽을 수 없이 짧은 자막을 만들지 않습니다.
    limit = max(1, int(duration // rules.min_duration))
    # 용량은 어림값입니다. 줄 끝 여백 때문에 실제 줄 수가 더 나올 수 있으므로
    # 줄바꿈 결과로 판정하고, 시간이 허락하는 만큼만 더 나눕니다.
    parts = min(max(math.ceil(len(text) / rules.capacity) if text else 1, 1), limit)
    chunks = split_text(text, parts) if parts > 1 else [text]
    while parts < limit and any(len(wrap_text(c, rules)) > rules.max_lines for c in chunks):
        parts += 1
        chunks = split_text(text, parts)
    if len(chunks) <= 1:
        return [cue.model_copy(update={"text": "\n".join(wrap_text(text, rules))})]

    spans = _allocate(cue.start, duration, chunks, rules)
    return [
        Cue(start=start, end=end, text="\n".join(wrap_text(chunk, rules)))
        for chunk, (start, end) in zip(chunks, spans, strict=True)
    ]


def _allocate(
    start: float, duration: float, chunks: list[str], rules: SubtitleRules
) -> list[tuple[float, float]]:
    """글자 수에 비례해 시간을 나눕니다. 한 조각이라도 너무 짧으면 균등 분할합니다."""
    total = sum(len(c) for c in chunks) or 1
    shares = [duration * len(c) / total for c in chunks]
    if any(s < rules.min_duration for s in shares):
        shares = [duration / len(chunks)] * len(chunks)
    spans: list[tuple[float, float]] = []
    cursor = start
    for index, share in enumerate(shares):
        end = start + duration if index == len(shares) - 1 else cursor + share
        spans.append((cursor, end))
        cursor = end
    return spans


def check(cues: list[Cue], rules: SubtitleRules = DEFAULT_RULES) -> list[Violation]:
    """고칠 곳을 보고합니다. 자동으로 고치지 않습니다."""
    found: list[Violation] = []
    for index, cue in enumerate(cues):
        duration = cue.end - cue.start
        text = normalize(cue.text.replace("\n", " "))
        lines = wrap_text(text, rules)
        if len(lines) > rules.max_lines:
            found.append(
                Violation(index, "lines", f"{len(lines)}줄이 필요합니다. 최대 {rules.max_lines}줄")
            )
        if duration > 0 and len(text) / duration > rules.max_cps:
            found.append(
                Violation(
                    index,
                    "cps",
                    f"초당 {len(text) / duration:.1f}자입니다. 최대 {rules.max_cps:.0f}자",
                )
            )
        if duration < rules.min_duration:
            found.append(Violation(index, "duration", f"{duration:.2f}초로 너무 짧습니다."))
        elif duration > rules.max_duration:
            found.append(Violation(index, "duration", f"{duration:.2f}초로 너무 깁니다."))
        if index + 1 < len(cues) and cues[index + 1].start < cue.end:
            found.append(Violation(index, "overlap", "다음 자막과 시간이 겹칩니다."))
    return found
