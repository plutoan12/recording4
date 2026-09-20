"""움직이는 자막: ASS 애니메이션 명령을 만듭니다.

libass가 지원하는 명령만 씁니다. `\\fad`(페이드), `\\t`(값 변화), `\\move`(이동),
`\\fscx`/`\\fscy`(크기), `\\frz`(회전), `\\alpha`(투명도)입니다. 자막 이벤트 전체에
붙는 것(등장·계속 움직임)과 글자·단어마다 붙는 것(타자기·단어별 등장·노래방 강조)으로
나뉩니다. 시각은 모두 이벤트 시작 기준 밀리초입니다.

글자·단어마다 붙이는 명령은 앞 조각의 상태가 뒤 조각으로 이어지는 ASS 규칙 때문에
조각마다 `\\r`로 스타일 값으로 되돌린 뒤 그때까지 나온 명령을 다시 적어 줍니다.
그렇지 않으면 첫 단어의 등장 명령이 둘째 단어에도 걸려 함께 나타납니다.

이 모듈은 템플릿 모델을 모릅니다. 템플릿(`subtitle_templates`)이 종류·시간·기준점을
넘겨 부릅니다.
"""

from __future__ import annotations

import re
from typing import Literal

__all__ = [
    "ANIMATION_DEFAULT_MS",
    "ANIMATION_LABELS",
    "CONTINUOUS",
    "ENTRANCE",
    "MOVING",
    "PER_RUN",
    "Animation",
    "animate_runs",
    "motion_tags",
    "tokens",
]

Animation = Literal[
    "none",
    "fade",
    "pop",
    "bounce",
    "slide-up",
    "slide-down",
    "zoom",
    "wiggle",
    "pulse",
    "typewriter",
    "word-pop",
    "karaoke",
]

ANIMATION_LABELS: dict[str, str] = {
    "none": "없음",
    "fade": "페이드",
    "pop": "팝(튀어나옴)",
    "bounce": "바운스(떨어져 통통)",
    "slide-up": "아래서 올라옴",
    "slide-down": "위에서 내려옴",
    "zoom": "천천히 커짐",
    "wiggle": "살랑살랑 흔들림",
    "pulse": "두근두근 맥박",
    "typewriter": "타자기(한 글자씩)",
    "word-pop": "단어별 등장",
    "karaoke": "노래방(말하는 단어 강조)",
}

# `animation_ms`를 비웠을 때의 값. 등장 효과는 등장에 걸리는 시간, 타자기는 글자 하나,
# 단어별 등장은 단어 하나, 흔들림·맥박은 한 주기입니다. 노래방은 자막 길이에 맞춰
# 단어를 고르게 나누므로 쓰지 않고, 천천히 커짐은 페이드 인 시간입니다.
ANIMATION_DEFAULT_MS: dict[str, int] = {
    "none": 0,
    "fade": 250,
    "pop": 320,
    "bounce": 520,
    "slide-up": 320,
    "slide-down": 320,
    "zoom": 250,
    "wiggle": 420,
    "pulse": 900,
    "typewriter": 60,
    "word-pop": 200,
    "karaoke": 0,
}

ENTRANCE = frozenset({"fade", "pop", "bounce", "slide-up", "slide-down", "zoom"})
CONTINUOUS = frozenset({"wiggle", "pulse"})
PER_RUN = frozenset({"typewriter", "word-pop", "karaoke"})
# `\move`를 써서 `\pos` 대신 자리를 정하는 것들.
MOVING = frozenset({"bounce", "slide-up", "slide-down"})

_MAX_SEGMENTS = 80
# 크기가 변하는 동안 libass가 줄을 다시 나누지 않게 합니다(줄바꿈은 규칙이 미리 정합니다).
_NO_WRAP = "\\q2"
_SLIDE_PX = 70
_DROP_PX = 90
_WIGGLE_DEG = 3.0


def _ms(value: float) -> int:
    return max(0, int(round(value)))


def motion_tags(
    kind: str,
    ms: int,
    *,
    duration_ms: int,
    anchor: tuple[float, float] | None,
    angle: float = 0,
    glow: float = 0,
) -> str:
    """이벤트 전체에 붙는 명령(중괄호 없이). 움직임이 없거나 조각별이면 빈 문자열.

    `anchor`는 글자가 정렬되는 점입니다. 이동이 필요한 움직임은 이 점을 목적지로
    `\\move`를 씁니다. 없으면 이동 없이 크기·투명도만 바꿉니다.
    """
    if duration_ms <= 0 or kind == "none" or kind in PER_RUN:
        return ""
    ms = min(_ms(ms), duration_ms) if kind not in CONTINUOUS else _ms(ms)
    if kind == "fade":
        edge = min(ms, duration_ms // 2)
        return f"\\fad({edge},{edge})"
    if kind == "pop":
        return _pop(ms)
    if kind == "bounce":
        if anchor is None:
            return _pop(ms)
        x, y = anchor
        land = _ms(ms * 0.5)
        squash = _ms(ms * 0.72)
        return (
            f"{_NO_WRAP}\\move({x:.0f},{y - _DROP_PX:.0f},{x:.0f},{y:.0f},0,{land})"
            f"\\t({land},{squash},\\fscx110\\fscy84)\\t({squash},{ms},\\fscx100\\fscy100)"
        )
    if kind in ("slide-up", "slide-down"):
        fade = f"\\fad({_ms(ms * 0.6)},0)"
        if anchor is None:
            return fade
        x, y = anchor
        offset = _SLIDE_PX if kind == "slide-up" else -_SLIDE_PX
        return f"\\move({x:.0f},{y + offset:.0f},{x:.0f},{y:.0f},0,{ms})" + fade
    if kind == "zoom":
        return f"{_NO_WRAP}\\fad({ms},0)\\t(0,{duration_ms},\\fscx110\\fscy110)"
    if kind == "wiggle":
        return _wiggle(ms, duration_ms, angle)
    if kind == "pulse":
        return _pulse(ms, duration_ms, glow)
    raise ValueError(f"모르는 움직임입니다: {kind}")


def _pop(ms: int) -> str:
    over = _ms(ms * 0.6)
    return (
        f"{_NO_WRAP}\\fscx40\\fscy40"
        f"\\t(0,{over},\\fscx112\\fscy112)\\t({over},{ms},\\fscx100\\fscy100)"
    )


def _period(ms: int, duration_ms: int) -> int:
    """반 주기(ms). 자막이 길어도 명령 수가 한계를 넘지 않게 주기를 늘립니다."""
    half = max(40, ms // 2)
    if duration_ms / half > _MAX_SEGMENTS:
        half = -(-duration_ms // _MAX_SEGMENTS)
    return half


def _wiggle(ms: int, duration_ms: int, angle: float) -> str:
    half = _period(ms, duration_ms)
    tags = [f"\\frz{angle + _WIGGLE_DEG:g}"]
    t, sign = 0, -1
    while t < duration_ms:
        tags.append(f"\\t({t},{t + half},\\frz{angle + sign * _WIGGLE_DEG:g})")
        t += half
        sign = -sign
    return "".join(tags)


def _pulse(ms: int, duration_ms: int, glow: float) -> str:
    half = _period(ms, duration_ms)
    up = "\\fscx105\\fscy105" + (f"\\blur{glow * 2.5:g}" if glow else "")
    down = "\\fscx100\\fscy100" + (f"\\blur{glow:g}" if glow else "")
    tags = [_NO_WRAP]
    t, rising = 0, True
    while t < duration_ms:
        tags.append(f"\\t({t},{t + half},{up if rising else down})")
        t += half
        rising = not rising
    return "".join(tags)


# ---------------------------------------------------------------- 조각별 명령

_TOKEN = re.compile(r"\{[^{}]*\}|\\[Nnh]|.", re.DOTALL)


def tokens(ass_text: str) -> list[str]:
    """이벤트 글자를 명령 묶음(`{...}`), 줄바꿈(`\\N`), 글자 하나로 나눕니다."""
    return _TOKEN.findall(ass_text)


def _is_override(token: str) -> bool:
    return token.startswith("{")


def _is_break(token: str) -> bool:
    return token in ("\\N", "\\n")


def _is_space(token: str) -> bool:
    return token == "\\h" or (len(token) == 1 and token.isspace())


def _alpha(hollow: bool, value: str) -> str:
    """외곽선·그림자(·채움) 투명도 명령. 속 빈 글자는 채움을 투명한 채로 둡니다."""
    parts = "" if hollow else f"\\1a&H{value}&"
    return f"\\3a&H{value}&\\4a&H{value}&" + parts


def _words(items: list[str]) -> list[list[int]]:
    """단어마다 토큰 번호 목록. 공백·줄바꿈이 단어를 나누고 명령 묶음은 다음 단어에 붙습니다."""
    words: list[list[int]] = []
    current: list[int] = []
    pending: list[int] = []
    for index, token in enumerate(items):
        if _is_override(token):
            pending.append(index)
        elif _is_space(token) or _is_break(token):
            if current:
                words.append(current)
                current = []
            pending = []
        else:
            if not current:
                current = pending
                pending = []
            current.append(index)
    if current:
        words.append(current)
    return words


def animate_runs(
    kind: str,
    ass_text: str,
    ms: int,
    *,
    duration_ms: int,
    prefix: str = "",
    hollow: bool = False,
    accent: str = "",
    base: str = "",
) -> str:
    """글자·단어마다 명령을 넣습니다. `kind`가 조각별 움직임이 아니면 그대로 돌려줍니다.

    `prefix`는 이 이벤트(층)에 이미 붙어 있는 명령(중괄호 없이)으로, `\\r` 뒤에 다시
    적어 층의 모양을 지킵니다. 노래방은 `accent`(강조 색 명령)와 `base`(원래 색 명령)가
    필요합니다.
    """
    if kind not in PER_RUN or duration_ms <= 0:
        return ass_text
    items = tokens(ass_text)
    if kind == "typewriter":
        return _typewriter(items, _ms(ms), duration_ms, prefix, hollow)
    words = _words(items)
    if not words:
        return ass_text
    if kind == "word-pop":
        return _word_pop(items, words, _ms(ms), duration_ms, prefix, hollow)
    return _karaoke(items, words, duration_ms, prefix, accent, base)


def _state_before(items: list[str], index: int, prefix: str) -> str:
    """`\\r` 뒤에 다시 적을 명령: 층의 명령과 이 조각 앞까지 나온 명령 묶음의 내용."""
    inner = [item[1:-1] for item in items[:index] if _is_override(item)]
    return "\\r" + prefix + "".join(inner)


def _typewriter(items: list[str], ms: int, duration_ms: int, prefix: str, hollow: bool) -> str:
    visible = [i for i, token in enumerate(items) if _visible(token)]
    if not visible:
        return "".join(items)
    step = max(1, min(ms, int(duration_ms * 0.7 / len(visible))))
    out: list[str] = []
    order = {index: n for n, index in enumerate(visible)}
    for index, token in enumerate(items):
        if index in order:
            at = order[index] * step
            out.append(
                "{"
                + _state_before(items, index, prefix)
                + _alpha(hollow, "FF")
                + f"\\t({at},{at + 1},{_alpha(hollow, '00')})"
                + "}"
            )
        out.append(token)
    return "".join(out)


def _visible(token: str) -> bool:
    return not (_is_override(token) or _is_break(token) or _is_space(token))


def _word_pop(
    items: list[str],
    words: list[list[int]],
    ms: int,
    duration_ms: int,
    prefix: str,
    hollow: bool,
) -> str:
    step = max(1, min(ms, int(duration_ms * 0.6 / len(words))))
    settle = max(60, min(ms, 220))
    lead: dict[int, str] = {}
    for n, word in enumerate(words):
        first = next(i for i in word if not _is_override(items[i]))
        at = n * step
        lead[first] = (
            "{"
            + _state_before(items, first, prefix)
            + _alpha(hollow, "FF")
            + f"\\t({at},{at + 1},{_alpha(hollow, '00')})"
            + f"\\fscy130\\t({at},{at + settle},\\fscy100)"
            + "}"
        )
    return "".join(lead.get(i, "") + token for i, token in enumerate(items))


def _karaoke(
    items: list[str],
    words: list[list[int]],
    duration_ms: int,
    prefix: str,
    accent: str,
    base: str,
) -> str:
    if not accent or not base:
        raise ValueError("노래방 강조에는 강조 색과 원래 색 명령이 필요합니다.")
    step = duration_ms / len(words)
    lead: dict[int, str] = {}
    for n, word in enumerate(words):
        first = next(i for i in word if not _is_override(items[i]))
        start = _ms(n * step)
        tags = _state_before(items, first, prefix) + f"\\t({start},{start + 1},{accent})"
        if n + 1 < len(words):
            end = _ms((n + 1) * step)
            tags += f"\\t({end},{end + 1},{base})"
        lead[first] = "{" + tags + "}"
    return "".join(lead.get(i, "") + token for i, token in enumerate(items))
