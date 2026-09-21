"""겹말 찾기와 표시. 오디오도 모델도 없이 시각만 봅니다.

이 계산이 틀리면 화자별 전사가 엉뚱한 자막에 '겹침'을 붙이거나, 진짜 겹친
자막을 멀쩡하다고 내보냅니다. 그래서 따로 고정합니다.
"""

from __future__ import annotations

import pytest

from pipeline.editing import Cue
from pipeline.overlap import (
    coverage,
    flag_overlaps,
    inside,
    merge,
    overlap_regions,
    overlapped_fraction,
    pick_speaker,
    speaker_spans,
)
from pipeline.speakers import SpeakerTurn


def turn(start: float, end: float, who: str) -> SpeakerTurn:
    return SpeakerTurn(start=start, end=end, speaker=who)


def cue(start: float, end: float) -> Cue:
    return Cue(start=start, end=end, text="말")


# --- 겹말 구간 찾기 --------------------------------------------------------


def test_two_speakers_talking_at_once_is_an_overlap() -> None:
    """이게 요점입니다. A가 0~10, B가 6~14면 6~10이 겹말입니다."""
    assert overlap_regions([turn(0, 10, "A"), turn(6, 14, "B")]) == [(6.0, 10.0)]


def test_speakers_taking_turns_have_no_overlap() -> None:
    assert overlap_regions([turn(0, 5, "A"), turn(5, 10, "B"), turn(10, 15, "A")]) == []


def test_the_same_speaker_split_in_two_is_not_an_overlap() -> None:
    """분리기가 한 사람의 말을 두 조각으로 줬을 뿐입니다. 겹말이 아닙니다."""
    assert overlap_regions([turn(0, 8, "A"), turn(5, 12, "A")]) == []


def test_touching_turns_are_not_an_overlap() -> None:
    """A가 5.0에 끝나고 B가 5.0에 시작하면 겹친 것이 아닙니다."""
    assert overlap_regions([turn(0, 5, "A"), turn(5, 10, "B")]) == []


def test_three_speakers_produce_one_merged_region() -> None:
    """A 0~10, B 4~8, C 7~12: 4~8은 A·B, 8~10은 A·C가 겹칩니다. 10~12는 C 혼자라
    겹말이 아닙니다. (처음에 4~12라고 적었다가 틀린 것을 잡았습니다.)"""
    turns = [turn(0, 10, "A"), turn(4, 8, "B"), turn(7, 12, "C")]
    assert overlap_regions(turns) == [(4.0, 10.0)]


def test_a_fully_contained_interruption_is_found() -> None:
    """B가 A의 말 한가운데 끼어들었다 빠지는 경우입니다."""
    assert overlap_regions([turn(0, 20, "A"), turn(8, 11, "B")]) == [(8.0, 11.0)]


# --- 화자 구간과 표시 ------------------------------------------------------


def test_speaker_spans_keep_the_overlapped_part() -> None:
    """겹친 시간에도 그 사람은 말하고 있었습니다. 지우면 그 말이 사라집니다."""
    turns = [turn(0, 10, "A"), turn(6, 14, "B")]
    assert speaker_spans(turns, "A") == [(0.0, 10.0)]
    assert speaker_spans(turns, "B") == [(6.0, 14.0)]


def test_merge_joins_overlapping_and_touching_spans() -> None:
    assert merge([(0, 3), (2, 5), (5, 6), (8, 9)]) == [(0.0, 6.0), (8.0, 9.0)]
    assert merge([(3, 3), (5, 4)]) == []


def test_a_cue_mostly_inside_the_overlap_is_flagged() -> None:
    regions = [(6.0, 10.0)]
    assert overlapped_fraction(cue(7, 9), regions) == pytest.approx(1.0)
    assert flag_overlaps([cue(7, 9)], regions) == [True]


def test_a_cue_barely_touching_the_overlap_is_not_flagged() -> None:
    """끝자락 0.2초가 걸친 5초 자막에 표시를 붙이면 멀쩡한 자막 대부분에 붙습니다."""
    regions = [(9.8, 12.0)]
    assert overlapped_fraction(cue(5, 10), regions) == pytest.approx(0.04)
    assert flag_overlaps([cue(5, 10)], regions) == [False]


def test_the_flag_threshold_is_the_fraction_not_the_seconds() -> None:
    """짧은 자막은 짧게 걸쳐도 비율이 큽니다."""
    regions = [(9.5, 12.0)]
    assert flag_overlaps([cue(9, 10)], regions) == [True]  # 0.5/1.0
    assert flag_overlaps([cue(0, 10)], regions) == [False]  # 0.5/10


def test_a_cue_where_the_speaker_never_spoke_is_outside() -> None:
    """무음에 지어낸 글입니다. 그 화자의 자막이 아닙니다."""
    spans = [(0.0, 5.0), (10.0, 15.0)]
    assert inside(cue(1, 3), spans)
    assert inside(cue(4, 11), spans)
    assert not inside(cue(6, 9), spans)


# --- 검증에서 쓰는 것 ------------------------------------------------------


def test_pick_speaker_finds_the_voice_we_know() -> None:
    """검증에서 '우리 원문의 그 사람'이 분리 결과의 어느 표시인지 골라야 합니다."""
    turns = [turn(0, 10, "SPEAKER_00"), turn(6, 14, "SPEAKER_01")]
    assert pick_speaker(turns, [(0.0, 4.0)]) == "SPEAKER_00"
    assert pick_speaker(turns, [(11.0, 14.0)]) == "SPEAKER_01"
    assert pick_speaker(turns, [(20.0, 25.0)]) is None


def test_coverage_rewards_marking_the_right_time_only() -> None:
    truth = [(6.0, 10.0)]
    assert coverage([(6.0, 10.0)], truth) == (pytest.approx(1.0), pytest.approx(1.0))
    # 절반만 표시: 정밀도 1, 재현율 0.5
    assert coverage([(6.0, 8.0)], truth) == (pytest.approx(1.0), pytest.approx(0.5))
    # 전부 표시: 재현율 1이지만 정밀도가 무너집니다
    precision, recall = coverage([(0.0, 40.0)], truth)
    assert recall == pytest.approx(1.0) and precision == pytest.approx(0.1)
    # 아무것도 표시하지 않음
    assert coverage([], truth) == (0.0, 0.0)


# --- 오디오 가리기 (numpy) ---------------------------------------------------


def test_masking_keeps_only_the_speakers_time() -> None:
    """화자 구간 밖이 0이 되고, 안은 그대로여야 합니다."""
    np = pytest.importorskip("numpy")
    from worker.analysis import mask_outside

    rate = 10
    audio = np.arange(1, 41, dtype=float)  # 4초, 초당 10표본
    kept = mask_outside(audio, [(1.0, 2.0), (3.0, 3.5)], rate=rate)
    assert kept[:10].tolist() == [0.0] * 10
    assert kept[10:20].tolist() == audio[10:20].tolist()
    assert kept[20:30].tolist() == [0.0] * 10
    assert kept[30:35].tolist() == audio[30:35].tolist()
    assert kept[35:].tolist() == [0.0] * 5
    # 원본은 건드리지 않습니다.
    assert audio[0] == 1.0


def test_masking_clamps_spans_past_the_end() -> None:
    np = pytest.importorskip("numpy")
    from worker.analysis import mask_outside

    audio = np.ones(20)
    kept = mask_outside(audio, [(1.5, 99.0)], rate=10)
    assert kept.sum() == 5
