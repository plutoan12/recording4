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
