"""자막 가독성 규칙.

순수 계산만 둡니다. 한국어 문장 분리는 kss가 설치되어 있으면 쓰고, 없으면
구두점 기준으로 내려갑니다. 어느 경우에도 글자를 버리지 않습니다.

용량이 넘치는 자막은 여러 자막으로 나눕니다. 초당 글자수(CPS)는 나눈다고
줄어들지 않으므로(같은 글자를 같은 시간에 읽습니다) 검사로만 보고합니다.

글자 수는 폭으로 셉니다. 한글·한자·가나는 1자, 라틴 문자·숫자·공백·문장부호는
0.5자입니다. Netflix 한국어 자막 지침의 계산 방식을 따랐습니다. 출처와 기본값
근거는 docs/OPEN_SOURCE_INTEGRATIONS.md에 있습니다.
"""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

from pipeline.editing import Cue

_SENTENCE_END = re.compile(r"(?<=[.!?…。！？])\s+")
_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class SubtitleRules:
    """자막 표시 규칙. 길이 단위는 글자 폭입니다(한글 1자, 라틴·공백 0.5자).

    기본값은 Netflix 한국어 자막 지침 I부(일반 번역 자막, 성인물)입니다.
    읽기 속도 12자/초는 I.15의 한도이며, 14자/초는 SDH(II.3)에서만 허용하는
    상향값이라 기본값으로 쓰지 않습니다. 최소 표시 시간만 지침의 5/6초 대신
    1초로 더 보수적으로 둡니다. 숏폼은 화면과 글꼴이 달라 측정 후 조정할 수
    있도록 모두 설정으로 노출합니다.
    """

    max_chars_per_line: int = 16
    max_lines: int = 2
    max_cps: float = 12.0
    min_duration: float = 1.0
    max_duration: float = 7.0

    @property
    def capacity(self) -> float:
        """자막 하나가 담을 수 있는 최대 글자 폭."""
        return self.max_chars_per_line * self.max_lines

    def __post_init__(self) -> None:
        if self.max_chars_per_line < 1 or self.max_lines < 1:
            raise ValueError("줄 길이와 줄 수는 1 이상이어야 합니다.")
        if self.max_cps <= 0 or self.min_duration <= 0 or self.max_duration <= 0:
            raise ValueError("CPS와 표시 시간은 0보다 커야 합니다.")


DEFAULT_RULES = SubtitleRules()

# 언어별 기본값. 값은 모두 글자 폭 단위입니다(한글 1자, 라틴·공백 0.5자).
#
# 지침 숫자는 언어마다 다른데, 우리 기본값은 한국어 지침에서 왔습니다. 그대로
# 영어 자막에 쓰면 줄당 16폭 = 영어 32자로 나와 지침(42자)보다 짧게 쪼개지고,
# 초당 12폭 = 영어 24자로 나와 지침(20자)보다 느슨해집니다. 그래서 언어마다
# 그 언어 지침을 폭 단위로 옮겨 둡니다.
LANGUAGE_RULES: dict[str, SubtitleRules] = {
    # Netflix 한국어 지침 I.2/I.15: 줄당 16자, 초당 12자.
    "ko": DEFAULT_RULES,
    # Netflix 영어 지침 줄당 42자는 가로 화면 기준입니다. 우리는 세로 숏폼
    # (1080px)에 글자 크기 64를 쓰므로 CI가 렌더해서 확인합니다(한도만큼 채운
    # 한 줄이 여백 980px 안에 들어가는지). 38자(폭 19)로 둡니다. 읽기 속도는
    # 지침대로 초당 20자(폭 10.0)입니다.
    "en": SubtitleRules(max_chars_per_line=19, max_cps=10.0),
}


def rules_for(language: str | None, base: SubtitleRules = DEFAULT_RULES) -> SubtitleRules:
    """목표 언어에 맞는 규칙.

    설정을 건드리지 않았으면 언어 기본값을 씁니다. 설정으로 바꿨다면 그
    값이 사람의 결정이므로 언어와 무관하게 그대로 둡니다. 모르는 언어도
    받은 값을 그대로 씁니다. 추측해서 바꾸지 않습니다.
    """
    if base != DEFAULT_RULES or not language:
        return base
    return LANGUAGE_RULES.get(language.split("-")[0].lower(), base)


Kind = Literal["cps", "lines", "duration", "overlap"]


@dataclass(frozen=True, slots=True)
class Violation:
    """사람이 고쳐야 하는 자막 문제. 자동으로 글자를 줄이지 않습니다."""

    index: int
    kind: Kind
    detail: str


def normalize(text: str) -> str:
    return _WHITESPACE.sub(" ", text).strip()


def char_width(char: str) -> float:
    """글자 하나의 폭. 전각(한글·한자·가나)은 1자, 나머지는 0.5자입니다."""
    return 1.0 if unicodedata.east_asian_width(char) in ("W", "F") else 0.5


def text_width(text: str) -> float:
    """문자열의 글자 폭 합. 줄 길이와 CPS 계산의 기준입니다."""
    return sum(char_width(c) for c in text)


# Keep numeric values/units and short Japanese endings together at line and cue cuts.
_PROTECTED = re.compile(
    r"[$€£¥]?[+-]?\d+(?:[.,:]\d+)*(?:\s?(?:AM|PM|a\.m\.|p\.m\.|美元|ドル|달러|초|秒|時|点|%))?"
    r"|から|ください|でした|です|ます",
    re.IGNORECASE,
)


def _safe_cut(text: str, index: int, limit: float) -> int:
    for match in _PROTECTED.finditer(text):
        if match.start() < index < match.end() and text_width(match.group()) <= limit:
            return match.start() or match.end()
    return index


def _cut(token: str, limit: float) -> tuple[str, str]:
    """폭 제한을 넘지 않는 앞부분과 남은 부분으로 자릅니다."""
    used = 0.0
    for index, char in enumerate(token):
        width = char_width(char)
        if used + width > limit:
            # 첫 글자부터 넘치면 한 글자는 넣습니다. 무한 반복을 막습니다.
            index = _safe_cut(token, index or 1, limit)
            return token[:index], token[index:]
        used += width
    return token, ""


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


def _words(text: str) -> list[str]:
    return re.split(r" (?!(?:AM|PM|a\.m\.|p\.m\.)(?:\s|$|[.,]))", text, flags=re.I)


def wrap_text(text: str, rules: SubtitleRules = DEFAULT_RULES) -> list[str]:
    """줄 길이에 맞춰 줄바꿈합니다. 공백이 없으면 글자 단위로 자릅니다.

    줄 수 제한은 여기서 강제하지 않습니다. 넘치면 check가 보고합니다.
    """
    limit = float(rules.max_chars_per_line)
    lines: list[str] = []
    current = ""
    for token in _words(normalize(text)):
        while text_width(token) > limit:
            if current:
                lines.append(current)
                current = ""
            head, token = _cut(token, limit)
            lines.append(head)
        if not token:
            continue
        candidate = f"{current} {token}" if current else token
        if text_width(candidate) > limit and current:
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
    for tokens, joiner in ((sentences(text), " "), (_words(text), " ")):
        if len(tokens) >= parts:
            return _group(tokens, parts, joiner)
    return _cut_evenly(text, parts)


def _cut_evenly(text: str, parts: int) -> list[str]:
    """공백이 없을 때 폭이 고르도록 자릅니다. 글자는 버리지 않습니다."""
    chunks: list[str] = []
    rest = text
    for remaining in range(parts, 0, -1):
        if not rest:
            break
        if remaining == 1:
            chunks.append(rest)
            break
        head, rest = _cut(rest, math.ceil(text_width(rest) / remaining * 2) / 2)
        chunks.append(head)
    return chunks or [text]


def _group(tokens: list[str], parts: int, joiner: str) -> list[str]:
    total = sum(text_width(t) for t in tokens) + text_width(joiner) * (len(tokens) - 1)
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
        length += text_width(token) + text_width(joiner)
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
    parts = min(max(math.ceil(text_width(text) / rules.capacity) if text else 1, 1), limit)
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
    total = sum(text_width(c) for c in chunks) or 1
    shares = [duration * text_width(c) / total for c in chunks]
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
        if duration > 0 and text_width(text) / duration > rules.max_cps:
            found.append(
                Violation(
                    index,
                    "cps",
                    f"초당 {text_width(text) / duration:.1f}자입니다. 최대 {rules.max_cps:.0f}자",
                )
            )
        if duration < rules.min_duration:
            found.append(Violation(index, "duration", f"{duration:.2f}초로 너무 짧습니다."))
        elif duration > rules.max_duration:
            found.append(Violation(index, "duration", f"{duration:.2f}초로 너무 깁니다."))
        if index + 1 < len(cues) and cues[index + 1].start < cue.end:
            found.append(Violation(index, "overlap", "다음 자막과 시간이 겹칩니다."))
    return found
