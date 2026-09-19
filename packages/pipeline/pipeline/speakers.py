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
