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


# 0x2600~0x27BF 블록은 한글 글꼴에 있는 기호(★☆♡♥♪✳✦✧)와 이모지가 섞여 있습니다.
# 이 블록에서는 여기 적힌 것만 이모지로 봅니다. 나머지는 템플릿 글꼴로 그립니다.
_SYMBOL_BLOCK_EMOJI = frozenset(
    "☀☁☂☃☔⚡⚽⚾⛄⛅⛈⛔⛪⛲⛳⛵⛺⛽✅✈✉✊✋✌✏✒✔✖✨❄❇❌❎❓❔❕❗❣❤➕➖➗➡⤴⤵"
)
_OTHER_EMOJI = frozenset("⭐⭕⌚⌛⏰⬆⬇⬅©®™")


def is_emoji(char: str) -> bool:
    """이모지로 볼 글자. 한글 글꼴에 있는 기호(★☆♡ 등)는 이모지로 보지 않습니다."""
    code = ord(char)
    if 0x1F000 <= code <= 0x1FAFF:
        return True
    if code == 0xFE0F:  # 이모지 표시 선택자. 앞 글자에 붙어 다닙니다.
        return True
    return char in _SYMBOL_BLOCK_EMOJI or char in _OTHER_EMOJI


def split_emoji(text: str) -> list[tuple[str, bool]]:
    """(글자 조각, 이모지인지) 목록. 이모지 구간에 다른 글꼴을 붙이는 데 씁니다."""
    parts: list[tuple[str, bool]] = []
    for char in text:
        emoji = is_emoji(char)
        if parts and parts[-1][1] == emoji:
            parts[-1] = (parts[-1][0] + char, emoji)
        else:
            parts.append((char, emoji))
    return parts or [("", False)]
