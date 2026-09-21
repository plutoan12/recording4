"""말이 없는 구간을 빼고 남길 구간을 고릅니다. 여기에는 FFmpeg도 네트워크도 없습니다.

프레임마다 "말이 있다/없다"를 참·거짓으로 늘어놓고 세 가지를 합니다.

1. **여백**(`apply_margin`): 말 앞뒤를 조금 더 남깁니다. 딱 붙여 자르면 첫소리가 잘립니다.
2. **다듬기**(`smooth`): 너무 짧은 남김과 너무 짧은 잘림을 없앱니다. 0.2초짜리 컷이 여러
   번 들어가면 영상이 덜컥거립니다.
3. 참이 이어지는 자리를 시각 구간으로 바꿉니다(`spans`).

1과 2는 auto-editor(퍼블릭 도메인)의 `mutMargin`·`smoothing`을 옮긴 것입니다. 출처는
THIRD_PARTY_NOTICES.md에 적었습니다.

**"말이 있다"는 판정은 여기서 하지 않습니다.** auto-editor와 jumpcutter는 프레임별 소리
크기를 임계값과 견주는데, 이 저장소는 실제 녹음에서 그 방법이 발화를 못 찾는 것을 이미
쟀습니다(`worker.analysis.vad_spans` 주석: 무음 감지로는 자막이 1.57초 늦게 시작). 그래서
발화 구간은 VAD가 찾고, 여기서는 그 구간을 다듬기만 합니다.

**여기서 나오는 것은 제안입니다.** 적용은 사람이 편집 화면에서 누릅니다.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

# 기본값. 초 단위이고, 프레임 수로 바꿔 씁니다. 잰 값이 아니라 정한 값입니다.
DEFAULT_FPS = 25
DEFAULT_MARGIN = 0.2
DEFAULT_MIN_CUT = 0.5
DEFAULT_MIN_CLIP = 0.4


def apply_margin(loud: Sequence[bool], start_margin: int, end_margin: int) -> list[bool]:
    """말 구간의 앞뒤를 넓히거나(양수) 좁힙니다(음수). 자리는 원본 기준으로 먼저 찾습니다."""
    arr = list(loud)
    starts = [j for j in range(1, len(arr)) if arr[j] and not arr[j - 1]]
    ends = [j for j in range(1, len(arr)) if not arr[j] and arr[j - 1]]
    for index in starts:
        if start_margin > 0:
            for k in range(max(index - start_margin, 0), index):
                arr[k] = True
        elif start_margin < 0:
            for k in range(index, min(index - start_margin, len(arr))):
                arr[k] = False
    for index in ends:
        if end_margin > 0:
            for k in range(index, min(index + end_margin, len(arr))):
                arr[k] = True
        elif end_margin < 0:
            for k in range(max(index + end_margin, 0), index):
                arr[k] = False
    return arr


def _fill_short_runs(source: list[bool], target: list[bool], want: bool, shortest: int) -> None:
    """`want`가 `shortest`보다 짧게 이어지는 자리를 반대 값으로 채웁니다."""
    start, active = 0, False
    for index, value in enumerate(source):
        if value == want:
            if not active:
                start, active = index, True
            # 마지막 칸은 여기서 끝나므로 길이에 1을 더해 셉니다.
            if index == len(source) - 1 and index - start + 1 < shortest:
                for i in range(start, len(source)):
                    target[i] = not want
        elif active:
            if index - start < shortest:
                for i in range(start, index):
                    target[i] = not want
            active = False


def smooth(loud: Sequence[bool], min_cut: int, min_clip: int) -> list[bool]:
    """짧은 남김과 짧은 잘림을 없앱니다. 더 바뀌지 않을 때까지 되풀이합니다.

    둘 다보다 짧은 구간 하나는 참↔거짓을 영원히 오갈 수 있어, 두 번 전 상태까지
    견주어 그 굴레를 빠져나옵니다(auto-editor의 주석이 지적한 것과 같은 이유입니다).
    """
    value, previous, previous2 = list(loud), None, None
    while value != previous and value != previous2:
        previous2, previous = previous, value
        nxt = list(previous)
        _fill_short_runs(previous, nxt, True, min_clip)
        _fill_short_runs(previous, nxt, False, min_cut)
        value = nxt
    return value


def frames_from_speech(
    speech: Sequence[tuple[float, float]], duration: float, fps: int = DEFAULT_FPS
) -> list[bool]:
    """발화 구간 목록을 프레임별 참·거짓으로 폅니다. 참이 말이 있는 자리입니다."""
    count = max(1, int(round(duration * fps)))
    loud = [False] * count
    for start, end in speech:
        for index in range(max(0, int(start * fps)), min(count, math.ceil(end * fps))):
            loud[index] = True
    return loud


def spans(loud: Sequence[bool], fps: int = DEFAULT_FPS) -> list[tuple[float, float]]:
    """참이 이어지는 자리를 (시작, 끝) 초로 바꿉니다."""
    found: list[tuple[float, float]] = []
    start: int | None = None
    for index, value in enumerate(loud):
        if value and start is None:
            start = index
        elif not value and start is not None:
            found.append((start / fps, index / fps))
            start = None
    if start is not None:
        found.append((start / fps, len(loud) / fps))
    return found


def keep_spans(
    speech: Sequence[tuple[float, float]],
    duration: float,
    *,
    fps: int = DEFAULT_FPS,
    margin: float = DEFAULT_MARGIN,
    min_cut: float = DEFAULT_MIN_CUT,
    min_clip: float = DEFAULT_MIN_CLIP,
) -> list[tuple[float, float]]:
    """발화 구간에서 남길 구간을 고릅니다. 시각은 소수점 셋째 자리까지입니다."""
    if duration <= 0:
        return []
    loud = frames_from_speech(speech, duration, fps)
    loud = apply_margin(loud, round(margin * fps), round(margin * fps))
    loud = smooth(loud, max(1, round(min_cut * fps)), max(1, round(min_clip * fps)))
    return [
        (round(start, 3), round(min(end, duration), 3))
        for start, end in spans(loud, fps)
        if min(end, duration) - start > 0
    ]


def kept_seconds(kept: Sequence[tuple[float, float]]) -> float:
    return round(sum(end - start for start, end in kept), 3)


def within(
    kept: Sequence[tuple[float, float]], start: float, end: float
) -> list[tuple[float, float]]:
    """고른 구간을 [start, end] 안으로 자릅니다. 숏폼 한 편에만 적용할 때 씁니다."""
    inside = []
    for first, last in kept:
        low, high = max(first, start), min(last, end)
        if high - low > 0:
            inside.append((round(low, 3), round(high, 3)))
    return inside
