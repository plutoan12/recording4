"""화자 구간을 자막에 붙이는 순수 계산.

화자 분리 자체는 워커의 WhisperX가 합니다. 여기서는 그 결과(화자 구간)와
대본(자막 구간)을 맞추는 규칙만 둡니다. 외부 의존성이 없어 테스트가 쉽습니다.
"""

from __future__ import annotations

from dataclasses import dataclass

from pipeline.editing import Cue


@dataclass(frozen=True, slots=True)
class SpeakerTurn:
    """화자 한 명이 말한 구간. 화자 표시는 공급자가 준 이름 그대로입니다."""

    start: float
    end: float
    speaker: str

    def __post_init__(self) -> None:
        if self.end <= self.start:
            raise ValueError("화자 구간 종료는 시작보다 뒤여야 합니다.")
        if not self.speaker:
            raise ValueError("화자 표시가 비어 있습니다.")


def _overlap(start: float, end: float, turn: SpeakerTurn) -> float:
    return max(0.0, min(end, turn.end) - max(start, turn.start))


def assign_speakers(cues: list[Cue], turns: list[SpeakerTurn]) -> list[str | None]:
    """자막마다 겹친 시간이 가장 긴 화자를 고릅니다.

    겹치는 화자가 없으면 `None`입니다. 추측해서 가까운 화자를 붙이지 않습니다.
    같은 시간이 겹치면 먼저 시작한 화자를 씁니다.
    """
    result: list[str | None] = []
    for cue in cues:
        best: tuple[float, float, str] | None = None
        for turn in turns:
            shared = _overlap(cue.start, cue.end, turn)
            if shared <= 0:
                continue
            candidate = (shared, -turn.start, turn.speaker)
            if best is None or candidate > best:
                best = candidate
        result.append(best[2] if best else None)
    return result


def speaker_totals(turns: list[SpeakerTurn]) -> dict[str, float]:
    """화자별 발화 시간 합. 어느 화자가 주 화자인지 화면에서 보여 줄 때 씁니다."""
    totals: dict[str, float] = {}
    for turn in turns:
        totals[turn.speaker] = totals.get(turn.speaker, 0.0) + (turn.end - turn.start)
    return dict(sorted(totals.items(), key=lambda item: (-item[1], item[0])))


def windows(
    spans: list[tuple[float, float]], *, length: float = 1.5, hop: float = 0.75
) -> list[tuple[float, float]]:
    """발화 구간을 일정한 길이의 창으로 자릅니다.

    한 구간 안에서 화자가 바뀔 수 있습니다. 구간을 통째로 한 목소리로 보면
    그 경계를 영영 찾지 못합니다. 창은 겹치게 잡습니다. 경계가 창 한가운데
    걸리면 그 창은 두 목소리가 섞여 어느 쪽으로도 잘 안 묶이는데, 겹쳐 두면
    이웃 창이 온전한 목소리를 담습니다.

    구간이 창보다 짧으면 그 구간을 그대로 하나로 씁니다. 버리지 않습니다.
    """
    if length <= 0 or hop <= 0:
        raise ValueError("창 길이와 간격은 0보다 커야 합니다.")
    cut: list[tuple[float, float]] = []
    for begin, finish in spans:
        if finish - begin <= length:
            cut.append((begin, finish))
            continue
        start = begin
        while start < finish:
            end = min(start + length, finish)
            # 마지막 조각이 너무 짧으면 앞 창에 흡수시킵니다.
            if finish - end < hop and cut and cut[-1][1] > start:
                cut[-1] = (cut[-1][0], finish)
                break
            cut.append((start, end))
            if end >= finish:
                break
            start += hop
    return cut


def _unit(vector: list[float]) -> list[float]:
    size = sum(value * value for value in vector) ** 0.5
    return [value / size for value in vector] if size else list(vector)


def _cosine(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=True))


def cluster(vectors: list[list[float]], count: int, *, rounds: int = 25) -> list[int]:
    """목소리 특징 벡터를 `count`개 묶음으로 나눕니다. 결과는 묶음 번호입니다.

    코사인 거리 k-평균입니다. 시작점은 무작위로 고르지 않고 서로 가장 먼
    벡터부터 차례로 고릅니다. 같은 음성을 두 번 재면 같은 답이 나와야
    검증에 쓸 수 있습니다.
    """
    if count < 1:
        raise ValueError("묶음 수는 1 이상이어야 합니다.")
    if not vectors:
        return []
    points = [_unit(v) for v in vectors]
    if count == 1 or len(points) <= count:
        return list(range(len(points))) if len(points) <= count else [0] * len(points)

    # 시작점은 이미 고른 것에서 가장 먼 점으로 차례로 잡습니다. 무작위로
    # 고르면 같은 음성을 두 번 재도 답이 달라집니다.
    centers = [points[0]]
    while len(centers) < count:
        centers.append(max(points, key=lambda p: min(1.0 - _cosine(p, c) for c in centers)))

    labels = [0] * len(points)
    for _ in range(rounds):
        moved = False
        for index, point in enumerate(points):
            best = max(range(count), key=lambda c: _cosine(point, centers[c]))
            if best != labels[index]:
                labels[index] = best
                moved = True
        for group in range(count):
            members = [p for p, label in zip(points, labels, strict=True) if label == group]
            if members:
                centers[group] = _unit([sum(values) for values in zip(*members, strict=True)])
        if not moved:
            break
    return labels


def turns_from_labels(
    spans: list[tuple[float, float]], labels: list[int], *, gap: float = 0.5
) -> list[SpeakerTurn]:
    """창과 묶음 번호를 화자 구간으로 합칩니다.

    같은 화자의 이웃 창은 하나로 잇습니다. 창을 겹쳐 잘랐으므로 이어 붙일 때
    겹친 부분은 자연히 사라집니다. `gap`보다 멀리 떨어지면 다른 구간입니다.
    """
    turns: list[SpeakerTurn] = []
    for (begin, finish), label in sorted(zip(spans, labels, strict=True), key=lambda item: item[0]):
        name = f"SPEAKER_{label:02d}"
        if turns and turns[-1].speaker == name and begin - turns[-1].end <= gap:
            turns[-1] = SpeakerTurn(
                start=turns[-1].start, end=max(turns[-1].end, finish), speaker=name
            )
            continue
        if finish > begin:
            turns.append(SpeakerTurn(start=begin, end=finish, speaker=name))
    return turns
