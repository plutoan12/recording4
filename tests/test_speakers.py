"""화자 배정 규칙. 순수 계산이라 외부 의존성 없이 검증합니다."""

from __future__ import annotations

import pytest

from pipeline.editing import Cue
from pipeline.speakers import SpeakerTurn, assign_speakers, speaker_totals


def test_turn_rejects_impossible_values() -> None:
    with pytest.raises(ValueError):
        SpeakerTurn(start=2, end=1, speaker="A")
    with pytest.raises(ValueError):
        SpeakerTurn(start=0, end=1, speaker="")


def test_cue_takes_the_speaker_it_overlaps_most() -> None:
    cues = [Cue(start=0, end=4, text="안녕하세요")]
    turns = [
        SpeakerTurn(start=0, end=1, speaker="A"),
        SpeakerTurn(start=1, end=4, speaker="B"),
    ]
    assert assign_speakers(cues, turns) == ["B"]


def test_cue_without_overlap_stays_unlabeled() -> None:
    """가까운 화자를 추측해서 붙이지 않습니다."""
    cues = [Cue(start=10, end=12, text="여기는 화자 구간 밖")]
    turns = [SpeakerTurn(start=0, end=5, speaker="A")]
    assert assign_speakers(cues, turns) == [None]


def test_ties_go_to_the_earlier_speaker() -> None:
    cues = [Cue(start=0, end=2, text="반반")]
    turns = [
        SpeakerTurn(start=1, end=2, speaker="B"),
        SpeakerTurn(start=0, end=1, speaker="A"),
    ]
    assert assign_speakers(cues, turns) == ["A"]


def test_each_cue_is_labeled_independently() -> None:
    cues = [
        Cue(start=0, end=2, text="첫 번째"),
        Cue(start=2, end=4, text="두 번째"),
        Cue(start=4, end=6, text="세 번째"),
    ]
    turns = [
        SpeakerTurn(start=0, end=2, speaker="A"),
        SpeakerTurn(start=2, end=4, speaker="B"),
        SpeakerTurn(start=4, end=6, speaker="A"),
    ]
    assert assign_speakers(cues, turns) == ["A", "B", "A"]


def test_no_turns_means_no_labels() -> None:
    assert assign_speakers([Cue(start=0, end=1, text="가")], []) == [None]


def test_totals_sum_per_speaker_in_descending_order() -> None:
    turns = [
        SpeakerTurn(start=0, end=1, speaker="A"),
        SpeakerTurn(start=1, end=4, speaker="B"),
        SpeakerTurn(start=4, end=5, speaker="A"),
    ]
    assert speaker_totals(turns) == {"B": 3.0, "A": 2.0}
    assert list(speaker_totals(turns)) == ["B", "A"]
