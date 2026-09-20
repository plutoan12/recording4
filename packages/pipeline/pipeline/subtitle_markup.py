"""자막 글자 안의 강조 표기 `[[...]]`.

편집기에서 `[[딸기]]말차라떼`처럼 적으면 굽는 자막에서 그 부분만 템플릿의 강조 색으로
그립니다. SRT·VTT 파일과 화면 표시에는 표기를 빼고 글자만 남깁니다. 이 모듈은
의존성이 없어 파일 내보내기(`subtitle_files`)와 템플릿(`subtitle_templates`)이 함께 씁니다.

닫히지 않은 `[[`는 줄 끝까지 강조로 보고, 짝 없는 `]]`는 글자에서 뺍니다. 표시 규칙이
긴 자막을 나눌 때 표기가 두 자막에 걸쳐 갈라져도 글자를 잃지 않게 하기 위해서입니다.
"""

from __future__ import annotations

import re

OPEN, CLOSE = "[[", "]]"
_MARKUP = re.compile(r"\[\[(.*?)(?:\]\]|$)", re.DOTALL)


def has_markup(text: str) -> bool:
    return OPEN in text or CLOSE in text


def strip_markup(text: str) -> str:
    """표기를 빼고 글자만 남깁니다. 파일 내보내기와 화면 표시에 씁니다."""
    return _MARKUP.sub(lambda m: m.group(1), text).replace(CLOSE, "")


def split_markup(text: str) -> list[tuple[str, bool]]:
    """(글자 조각, 강조 여부) 목록. 강조가 없으면 조각 하나입니다."""
    parts: list[tuple[str, bool]] = []
    cursor = 0
    for match in _MARKUP.finditer(text):
        if match.start() > cursor:
            parts.append((text[cursor : match.start()].replace(CLOSE, ""), False))
        if match.group(1):
            parts.append((match.group(1), True))
        cursor = match.end()
    if cursor < len(text):
        parts.append((text[cursor:].replace(CLOSE, ""), False))
    return [(piece, accent) for piece, accent in parts if piece] or [("", False)]
