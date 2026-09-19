"""겹말(두 사람이 동시에 말한 구간)을 찾고 자막에 표시하는 순수 계산.

전사는 겹말에서 무너집니다(실측: 끼어든 목소리가 5dB만 작아도 CER 92%). 디코딩
손잡이로도 분리 전처리로도 고쳐지지 않았습니다. 그래서 방향을 바꿉니다.
**못 알아듣는 구간을 알아듣는 척하지 말고, 어디가 겹쳤는지 찾아 표시합니다.**

화자 분리가 준 구간(`SpeakerTurn`)에서 두 화자 이상이 동시에 말한 시간을
찾습니다. 그 시간에 걸친 자막은 믿을 수 없다고 표시합니다. 화자별로 따로
받아쓸 때는 그 화자의 구간 밖을 무음으로 지우므로, 겹치지 않은 시간에는 남의
말이 들어갈 길이 없습니다.

여기에는 오디오도 모델도 없습니다. 시각 계산뿐이라 시험이 쉽습니다.
"""

from __future__ import annotations

from dataclasses import dataclass

from pipeline.editing import Cue
from pipeline.speakers import SpeakerTurn

Span = tuple[float, float]

# 자막 길이의 이만큼 이상이 겹말 시간에 걸치면 겹쳤다고 표시합니다. 끝자락이
# 살짝 걸친 것까지 표시하면 멀쩡한 자막 대부분에 표시가 붙습니다.
MIN_OVERLAP_FRACTION = 0.2


@dataclass(frozen=True, slots=True)
class SpokenCue:
    """화자별 전사 한 줄. 누가 말했고, 그때 다른 사람도 말하고 있었는지."""

    cue: Cue
    speaker: str
    overlap: bool


def merge(spans: list[Span]) -> list[Span]:
    """겹치거나 맞닿은 구간을 하나로 합칩니다."""
    merged: list[Span] = []
    for begin, finish in sorted(spans):
        if finish <= begin:
            continue
        if merged and begin <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], finish))
        else:
            merged.append((begin, finish))
    return merged


def speaker_spans(turns: list[SpeakerTurn], speaker: str) -> list[Span]:
    """이 화자가 말한 구간. 겹친 부분도 포함합니다. 거기서 남의 목소리를 지울
    방법은 없고, 대신 겹침 표시가 붙습니다."""
    return merge([(t.start, t.end) for t in turns if t.speaker == speaker])


def overlap_regions(turns: list[SpeakerTurn]) -> list[Span]:
    """두 화자 이상이 동시에 말한 구간.

    같은 화자의 구간끼리 겹친 것은 겹말이 아닙니다(분리기가 한 사람의 말을 두
    조각으로 줬을 뿐입니다). 화자가 다를 때만 셉니다.
    """
    edges: list[tuple[float, int, str]] = []
    for turn in turns:
        edges.append((turn.start, +1, turn.speaker))
        edges.append((turn.end, -1, turn.speaker))
    # 같은 시각이면 끝을 먼저 처리합니다. 맞닿은 두 구간은 겹친 것이 아닙니다.
    edges.sort(key=lambda edge: (edge[0], edge[1]))

    active: dict[str, int] = {}
    found: list[Span] = []
    opened: float | None = None
    for at, delta, speaker in edges:
        before = sum(1 for count in active.values() if count > 0)
        active[speaker] = active.get(speaker, 0) + delta
        after = sum(1 for count in active.values() if count > 0)
        if before < 2 <= after:
            opened = at
        elif before >= 2 > after and opened is not None:
            found.append((opened, at))
            opened = None
    return merge(found)


def shared(begin: float, finish: float, spans: list[Span]) -> float:
    """구간 [begin, finish)가 `spans`와 겹친 시간의 합."""
    return sum(max(0.0, min(finish, e) - max(begin, s)) for s, e in spans)


def overlapped_fraction(cue: Cue, regions: list[Span]) -> float:
    """이 자막 길이 중 겹말 시간에 걸친 비율."""
    length = cue.end - cue.start
    return shared(cue.start, cue.end, regions) / length if length > 0 else 0.0


def flag_overlaps(
    cues: list[Cue], regions: list[Span], *, min_fraction: float = MIN_OVERLAP_FRACTION
) -> list[bool]:
    """자막마다 겹말에 걸쳤는지."""
    return [overlapped_fraction(cue, regions) >= min_fraction for cue in cues]


def inside(cue: Cue, spans: list[Span]) -> bool:
    """이 자막이 화자의 구간과 조금이라도 겹치는지.

    화자 구간 밖을 무음으로 지운 오디오에서도 전사기는 가끔 무음에 글을
    지어냅니다. 그 화자가 말하지 않은 시각의 자막은 버려야 합니다.
    """
    return shared(cue.start, cue.end, spans) > 0.0


def pick_speaker(turns: list[SpeakerTurn], target: list[Span]) -> str | None:
    """`target` 구간과 가장 많이 겹친 화자. 검증에서 '이 사람이 우리가 아는
    그 목소리'를 고를 때 씁니다. 아무도 안 겹치면 None입니다."""
    best: tuple[float, str] | None = None
    for speaker in sorted({t.speaker for t in turns}):
        amount = sum(shared(s, e, target) for s, e in speaker_spans(turns, speaker))
        if amount > 0 and (best is None or amount > best[0]):
            best = (amount, speaker)
    return best[1] if best else None


def coverage(marked: list[Span], truth: list[Span]) -> tuple[float, float]:
    """(정밀도, 재현율). 표시한 시간 중 진짜 겹말인 비율, 진짜 겹말 중 표시된 비율.

    둘 다 봐야 합니다. 전부 표시하면 재현율은 1이지만 표시가 무의미해지고,
    하나도 안 하면 정밀도는 정의되지 않습니다(0으로 둡니다).
    """
    marked, truth = merge(marked), merge(truth)
    marked_total = sum(e - s for s, e in marked)
    truth_total = sum(e - s for s, e in truth)
    hit = sum(shared(s, e, truth) for s, e in marked)
    precision = hit / marked_total if marked_total > 0 else 0.0
    recall = hit / truth_total if truth_total > 0 else 0.0
    return precision, recall
