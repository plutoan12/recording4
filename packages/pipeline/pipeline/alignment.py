"""정렬기가 준 단어 시각을 줄 단위 자막으로 묶는 순수 계산.

정렬기에 줄 유지 옵션을 주면 문장은 나뉘지만 시각이 밀립니다(측정: 첫 자막이
1초 늦음). 옵션 없이 한 덩어리로 정렬하면 시각은 정확하지만 여러 문장이 한
자막으로 합쳐집니다. 그래서 정렬은 옵션 없이 돌리고, 줄 나누기는 여기서
단어 시각으로 직접 합니다.

글자는 건드리지 않습니다. 대본의 줄을 그대로 쓰고 시각만 가져옵니다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from pipeline.editing import Cue

_SPACE = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class WordTiming:
    """정렬기가 찾은 단어 하나의 시각."""

    start: float
    end: float
    text: str


def squeeze(text: str) -> str:
    """공백을 뺀 글자열. 정렬기는 공백 처리를 바꿀 수 있어도 글자는 못 바꿉니다."""
    return _SPACE.sub("", text)


def spans_from_timestamps(stamps: list, rate: int = 16000) -> list[tuple[float, float]]:
    """VAD가 준 발화 구간을 초 단위 (시작, 끝) 목록으로 바꿉니다.

    공급자 버전에 따라 표본 번호를 주기도 하고 초를 주기도 합니다. 값이
    너무 크면 표본 번호로 보고 나눕니다. 형식이 다르면 건너뜁니다.
    """

    def read(stamp, key: str) -> float | None:  # noqa: ANN001
        value = stamp.get(key) if isinstance(stamp, dict) else getattr(stamp, key, None)
        if value is None:
            return None
        number = float(value)
        # 초 단위로 1000을 넘는 지점은 16분이 넘습니다. 표본 번호로 봅니다.
        return number / rate if number > 1000 else number

    found: list[tuple[float, float]] = []
    for stamp in stamps:
        begin, finish = read(stamp, "start"), read(stamp, "end")
        if begin is None or finish is None or finish <= begin:
            continue
        found.append((begin, finish))
    return sorted(found)


def merge_spans(spans: list[tuple[float, float]], gap: float = 0.3) -> list[tuple[float, float]]:
    """짧게 끊긴 발화를 하나로 합칩니다.

    VAD는 한 문장 안에서도 숨이나 자음 사이를 끊어 여러 조각으로 줍니다.
    그 조각의 시작을 문장 시작으로 착각하면 자막을 엉뚱한 곳에 맞춥니다
    (측정: 자막 3이 앞 문장 중간에서 시작한 채 그대로 남음). `gap`보다 짧게
    떨어진 조각은 같은 발화로 봅니다.
    """
    merged: list[tuple[float, float]] = []
    for begin, finish in sorted(spans):
        if merged and begin - merged[-1][1] <= gap:
            merged[-1] = (merged[-1][0], max(merged[-1][1], finish))
        else:
            merged.append((begin, finish))
    return merged


def snap_starts(
    cues: list[Cue], spans: list[tuple[float, float]], *, window: float = 2.0, gap: float = 0.3
) -> list[Cue]:
    """자막 시작을 실제 발화가 시작되는 지점으로 맞춥니다.

    정렬기의 단어 시각은 무음 안쪽으로 당겨지기도 하고(측정: 합성 음성에서
    1.73초 이르게 시작) 발화 중간으로 밀리기도 합니다(측정: 사람 목소리에서
    1.57초 늦게 시작). 어느 쪽이든 자막이 말과 어긋납니다.

    앞 자막이 끝나기 전에 시작한 발화는 앞 자막의 몫이라 후보에서 뺍니다.
    남은 발화의 시작 중 가장 가까운 것으로 맞춥니다.

    옮겨도 되는 경우만 옮깁니다. `window`를 넘게 움직여야 하거나 자막이
    사라질 만큼 뒤로 가면 그대로 둡니다. 이 두 조건이 엉뚱한 발화로
    끌려가는 것을 막습니다.
    """
    if not spans:
        return cues
    # 문장 안에서 끊긴 조각을 먼저 합칩니다. 합치지 않으면 그 조각의 시작을
    # 문장 시작으로 착각합니다.
    ordered = merge_spans(spans, gap)
    result: list[Cue] = []
    previous_end = 0.0
    for cue in cues:
        # 앞 자막이 말하던 발화는 건너뜁니다. 이 자막의 말이 아닙니다.
        candidates = [begin for begin, _ in ordered if begin >= previous_end]
        target = min(candidates, key=lambda value: abs(value - cue.start), default=None)
        moved = (
            target
            if target is not None and abs(target - cue.start) <= window and target < cue.end
            else cue.start
        )
        result.append(cue if moved == cue.start else cue.model_copy(update={"start": moved}))
        previous_end = cue.end
    return result


def cues_for_lines(lines: list[str], words: list[WordTiming]) -> list[Cue] | None:
    """대본의 줄마다 자막 하나를 만듭니다. 맞출 수 없으면 None입니다.

    None을 돌려주면 부르는 쪽이 정렬기의 원래 구간을 그대로 씁니다. 억지로
    맞추다 글자나 시각이 틀어지느니 덜 나뉜 자막이 낫습니다.
    """
    kept = [line.strip() for line in lines if line.strip()]
    if not kept or not words:
        return None
    if squeeze("".join(kept)) != squeeze("".join(w.text for w in words)):
        # 정렬기가 글자를 바꿨거나 단어 목록이 빠졌습니다. 묶지 않습니다.
        return None

    cues: list[Cue] = []
    index = 0
    for line in kept:
        need = len(squeeze(line))
        got = 0
        first = index
        while index < len(words) and got < need:
            got += len(squeeze(words[index].text))
            index += 1
        # 단어 하나가 줄 경계를 넘어가면 시각을 쪼갤 수 없습니다.
        if got != need or first >= index:
            return None
        start, end = words[first].start, words[index - 1].end
        if end <= start:
            return None
        cues.append(Cue(start=start, end=end, text=line))
    if index != len(words):
        return None
    return cues
