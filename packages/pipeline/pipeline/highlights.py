"""LLM이 고른 하이라이트 구간을 **대본에 맞춰 보는** 자리. 망을 타지 않습니다.

`editing.suggest_clips`는 문장 경계로 자르는 규칙입니다. 무엇이 재미있는지는
모릅니다. 그걸 LLM에게 묻습니다. 문제는 **LLM이 없는 시각을 만들어낸다**는
것입니다. "12분 34초가 좋습니다"라는 답은 그럴듯하지만 거기에 그 말이 없을 수
있습니다.

그래서 **시각을 묻지 않습니다. 자막 번호를 묻습니다.** 번호를 받아 시각은
대본에서 꺼내 씁니다. 없는 번호는 그 자리에서 걸립니다. 지어낸 시각은 확인할
길이 없지만 지어낸 번호는 있습니다.

번호를 받아도 그대로 쓰지 않습니다. 길이·겹침·범위를 여기서 다시 봅니다.
**버린 것은 왜 버렸는지 함께 돌려줍니다.** 조용히 줄어든 목록은 모델이 잘한
건지 우리가 다 버린 건지 알 수 없습니다.

결과는 `suggest_clips`와 **같은 모양**입니다. 관리화면은 어느 쪽이 만든
후보인지 몰라도 됩니다. 두 쪽을 나란히 놓고 비교할 수도 있습니다.
"""

from __future__ import annotations

from dataclasses import dataclass

from pipeline.editing import Cue

# 한 번에 물어볼 수 있는 대본 크기. 넘으면 자르지 않고 거절합니다. 조용히
# 자르면 뒷부분이 통째로 후보에서 빠진 것을 아무도 모릅니다.
MAX_CUES = 800
MAX_CHARS = 60_000
# 숏폼 한 편의 길이. 위쪽 한계는 EditSpec과 같습니다.
MIN_SECONDS = 5.0
MAX_SECONDS = 180.0


@dataclass(frozen=True)
class Pick:
    """모델이 고른 것. **시각이 아니라 자막 번호입니다.**"""

    first: int
    last: int
    title: str = ""
    reason: str = ""


@dataclass(frozen=True)
class Rejected:
    """버린 후보와 그 이유. 사람이 읽습니다."""

    pick: Pick
    why: str


class TooMuchTranscript(ValueError):
    """대본이 한 번에 물어보기에 너무 큽니다."""


def ordered(cues: list[Cue]) -> list[Cue]:
    return sorted(cues, key=lambda c: (c.start, c.end))


def numbered(cues: list[Cue]) -> str:
    """모델에게 보낼 대본. 번호와 시각을 함께 보여 주되 답은 번호로 받습니다.

    시각을 보여 주는 이유는 길이를 가늠하게 하기 위해서입니다. 답에 시각이
    들어와도 쓰지 않습니다.
    """
    rows = ordered(cues)
    if len(rows) > MAX_CUES:
        raise TooMuchTranscript(f"자막이 {len(rows)}개입니다. {MAX_CUES}개까지만 물어봅니다.")
    body = "\n".join(f"{i}\t{c.start:.1f}\t{c.end:.1f}\t{c.text}" for i, c in enumerate(rows))
    if len(body) > MAX_CHARS:
        raise TooMuchTranscript(f"대본이 {len(body)}자입니다. {MAX_CHARS}자까지만 물어봅니다.")
    return body


def _fault(
    pick: Pick, count: int, span: tuple[float, float], duration: float, max_seconds: float
) -> str | None:
    """이 후보를 버려야 하는 이유. 버릴 것이 없으면 None."""
    if not 0 <= pick.first < count or not 0 <= pick.last < count:
        return f"대본에 없는 번호입니다(자막 0~{count - 1})."
    if pick.last < pick.first:
        return "끝 번호가 시작 번호보다 앞입니다."
    start, end = span
    if end > duration:
        return f"구간 끝({end:.1f}초)이 영상 길이({duration:.1f}초)를 넘습니다."
    length = end - start
    if length < MIN_SECONDS:
        return f"{length:.1f}초뿐입니다. {MIN_SECONDS:.0f}초는 넘어야 합니다."
    if length > max_seconds:
        return f"{length:.1f}초입니다. {max_seconds:.0f}초를 넘습니다."
    return None


def accept(
    cues: list[Cue],
    picks: list[Pick],
    *,
    duration: float,
    limit: int = 5,
    max_seconds: float = MAX_SECONDS,
) -> tuple[list[dict], list[Rejected]]:
    """고른 것을 대본에 맞춰 보고 (쓸 것, 버린 것)을 돌려줍니다.

    앞에 온 것을 먼저 씁니다. 모델이 매긴 순서가 곧 추천 순서입니다.
    """
    rows = ordered(cues)
    taken: list[dict] = []
    thrown: list[Rejected] = []
    for pick in picks:
        if len(taken) >= limit:
            thrown.append(Rejected(pick, f"{limit}개까지만 씁니다."))
            continue
        inside = 0 <= pick.first < len(rows) and 0 <= pick.last < len(rows)
        span = (
            (rows[pick.first].start, rows[pick.last].end)
            if inside and pick.last >= pick.first
            else (0.0, 0.0)
        )
        fault = _fault(pick, len(rows), span, duration, max_seconds)
        if fault:
            thrown.append(Rejected(pick, fault))
            continue
        start, end = span
        if any(start < used["end"] and end > used["start"] for used in taken):
            thrown.append(Rejected(pick, "이미 고른 구간과 겹칩니다."))
            continue
        title = (pick.title or rows[pick.first].text)[:100]
        why = pick.reason.strip() or "이유를 말하지 않았습니다."
        taken.append(
            {
                "start": start,
                "end": end,
                "title": title,
                # 어디서 온 제안인지 남깁니다. 규칙이 고른 것과 섞이기 때문입니다.
                "reason": f"LLM 추천(자막 {pick.first}~{pick.last}): {why}",
            }
        )
    return taken, thrown
