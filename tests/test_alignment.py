"""단어 시각을 줄 단위 자막으로 묶는 규칙. 순수 계산이라 모델이 필요 없습니다."""

from __future__ import annotations

from pipeline.alignment import WordTiming, cues_for_lines


def words(*items: tuple[float, float, str]) -> list[WordTiming]:
    return [WordTiming(start=s, end=e, text=t) for s, e, t in items]


def test_each_line_becomes_one_cue_with_its_own_times() -> None:
    cues = cues_for_lines(
        ["안녕하세요 반갑습니다", "두 번째 문장입니다"],
        words(
            (1.0, 1.8, " 안녕하세요"),
            (1.9, 2.6, " 반갑습니다"),
            (6.4, 6.9, " 두"),
            (7.0, 7.5, " 번째"),
            (7.6, 8.4, " 문장입니다"),
        ),
    )
    assert cues is not None
    assert [(c.start, c.end, c.text) for c in cues] == [
        (1.0, 2.6, "안녕하세요 반갑습니다"),
        (6.4, 8.4, "두 번째 문장입니다"),
    ]


def test_blank_lines_are_ignored() -> None:
    cues = cues_for_lines(
        ["첫 줄", "", "  ", "둘째 줄"],
        words((0.0, 1.0, "첫"), (1.0, 1.5, " 줄"), (2.0, 2.5, " 둘째"), (2.6, 3.0, " 줄")),
    )
    assert cues is not None
    assert [c.text for c in cues] == ["첫 줄", "둘째 줄"]


def test_word_crossing_a_line_boundary_gives_up() -> None:
    """한 단어가 두 줄에 걸치면 시각을 쪼갤 수 없습니다. 억지로 맞추지 않습니다."""
    assert cues_for_lines(["첫줄", "둘째줄"], words((0.0, 2.0, "첫줄둘째줄"))) is None


def test_missing_or_extra_words_give_up() -> None:
    assert cues_for_lines(["첫 줄", "둘째 줄"], words((0.0, 1.0, "첫 줄"))) is None
    assert cues_for_lines(["첫 줄"], words((0.0, 1.0, "첫 줄"), (1.0, 2.0, " 남는 단어"))) is None


def test_changed_letters_give_up() -> None:
    """정렬기가 글자를 바꿨다면 묶지 않습니다. 정렬은 전사가 아닙니다."""
    assert cues_for_lines(["안녕하세요"], words((0.0, 1.0, "안녕하십니까"))) is None


def test_zero_length_cue_gives_up() -> None:
    assert cues_for_lines(["한 줄"], words((2.0, 2.0, "한 줄"))) is None


def test_empty_input_gives_up() -> None:
    assert cues_for_lines([], words((0.0, 1.0, "가"))) is None
    assert cues_for_lines(["가"], []) is None


def test_late_start_snaps_back_to_its_own_speech() -> None:
    """발화 중간에서 시작한 자막을 그 발화의 시작으로 당깁니다.

    사람 목소리 측정에서 자막이 1.57초 늦게 시작한 경우입니다.
    """
    from pipeline.alignment import snap_starts
    from pipeline.editing import Cue

    cues = [Cue(start=14.58, end=20.54, text="두 번째 문장")]
    spans = [(1.08, 10.5), (13.01, 20.6)]
    assert [c.start for c in snap_starts(cues, spans)] == [13.01]


def test_early_start_snaps_forward_to_the_next_speech() -> None:
    """무음에서 시작한 자막을 다음 발화 시작으로 밉니다.

    합성 음성 측정에서 자막이 1.73초 이르게 시작한 경우입니다.
    """
    from pipeline.alignment import snap_starts
    from pipeline.editing import Cue

    cues = [Cue(start=10.5, end=16.5, text="마지막 문장")]
    spans = [(1.0, 5.45), (6.45, 11.23), (12.23, 17.06)]
    assert [c.start for c in snap_starts(cues, spans)] == [12.23]


def test_snap_does_not_jump_to_a_far_speech() -> None:
    """가까운 발화 시작을 찾지 않습니다. 엉뚱한 발화로 끌려가면 더 나쁩니다."""
    from pipeline.alignment import snap_starts
    from pipeline.editing import Cue

    cues = [Cue(start=6.4, end=11.0, text="문장")]
    # 4.88에서 시작하는 발화가 더 가깝지만 이 자막이 걸친 발화가 아닙니다.
    spans = [(0.5, 5.3), (6.05, 11.2)]
    assert [c.start for c in snap_starts(cues, spans)] == [6.05]


def test_far_speech_is_left_alone() -> None:
    """window를 넘게 움직여야 하면 그대로 둡니다."""
    from pipeline.alignment import snap_starts
    from pipeline.editing import Cue

    cues = [Cue(start=10.5, end=20.0, text="문장")]
    assert [c.start for c in snap_starts(cues, [(1.0, 5.0), (18.0, 19.5)])] == [10.5]


def test_snap_never_overlaps_the_previous_cue() -> None:
    from pipeline.alignment import snap_starts
    from pipeline.editing import Cue

    cues = [Cue(start=1.0, end=5.0, text="첫째"), Cue(start=5.2, end=9.0, text="둘째")]
    # 둘째 자막이 걸친 발화는 4.0에 시작하지만 첫째 자막이 아직 끝나지 않았습니다.
    assert [c.start for c in snap_starts(cues, [(1.0, 5.0), (4.0, 9.5)])] == [1.0, 5.2]


def test_snap_never_makes_a_cue_disappear() -> None:
    from pipeline.alignment import snap_starts
    from pipeline.editing import Cue

    cues = [Cue(start=3.0, end=4.0, text="짧은 자막")]
    # 4.5는 자막 끝을 넘어서므로 옮기지 않습니다.
    assert [c.start for c in snap_starts(cues, [(4.5, 6.0)])] == [3.0]


def test_no_spans_changes_nothing() -> None:
    from pipeline.alignment import snap_starts
    from pipeline.editing import Cue

    cues = [Cue(start=3.0, end=4.0, text="자막")]
    assert snap_starts(cues, []) == cues


def test_spans_from_timestamps_accepts_samples_and_seconds() -> None:
    """VAD 버전에 따라 표본 번호를 주기도 하고 초를 주기도 합니다."""
    from pipeline.alignment import spans_from_timestamps

    # 표본 번호(16kHz): 16000표본 = 1초
    assert spans_from_timestamps([{"start": 16000, "end": 32000}]) == [(1.0, 2.0)]
    # 초 단위로 주는 경우
    assert spans_from_timestamps([{"start": 1.0, "end": 2.0}]) == [(1.0, 2.0)]


def test_spans_from_timestamps_reads_objects_and_skips_junk() -> None:
    from types import SimpleNamespace

    from pipeline.alignment import spans_from_timestamps

    stamps = [SimpleNamespace(start=32000, end=48000), {"end": 5}, {"start": 16000}]
    # 시작이나 끝이 없는 항목은 버립니다.
    assert spans_from_timestamps(stamps) == [(2.0, 3.0)]


def test_spans_from_timestamps_sorts_and_drops_empty() -> None:
    from pipeline.alignment import spans_from_timestamps

    stamps = [
        {"start": 32000, "end": 48000},
        {"start": 16000, "end": 32000},
        {"start": 8, "end": 8},
    ]
    assert spans_from_timestamps(stamps) == [(1.0, 2.0), (2.0, 3.0)]


def test_merge_spans_joins_pieces_of_one_sentence() -> None:
    """VAD는 한 문장도 숨 사이에서 끊습니다. 0.3초 이내는 같은 발화로 봅니다."""
    from pipeline.alignment import merge_spans

    spans = [(1.0, 5.2), (5.3, 8.0), (10.5, 11.23), (12.23, 17.0)]
    assert merge_spans(spans) == [(1.0, 8.0), (10.5, 11.23), (12.23, 17.0)]


def test_merge_spans_keeps_sentence_gaps() -> None:
    """문장 사이 1초 무음은 그대로 둡니다. 합치면 경계를 잃습니다."""
    from pipeline.alignment import merge_spans

    assert merge_spans([(1.0, 5.45), (6.45, 11.23)]) == [(1.0, 5.45), (6.45, 11.23)]


def test_snap_ignores_a_split_inside_the_previous_sentence() -> None:
    """앞 문장이 VAD에서 쪼개져도 자막을 다음 문장 시작으로 맞춥니다.

    합성 음성 측정에서 자막 3이 10.50초에 머물러 1.73초 어긋난 경우입니다.
    """
    from pipeline.alignment import snap_starts
    from pipeline.editing import Cue

    cues = [
        Cue(start=6.44, end=10.50, text="두 번째 문장"),
        Cue(start=10.50, end=16.21, text="마지막 문장"),
    ]
    # VAD가 두 번째 문장을 10.4에서 끊어 조각을 하나 더 만들었습니다.
    spans = [(1.0, 5.45), (6.45, 10.38), (10.45, 11.23), (12.23, 17.06)]
    assert [c.start for c in snap_starts(cues, spans)] == [6.45, 12.23]


def test_supported_options_keeps_only_known_dataclass_fields():
    """공급자 버전에 없는 설정은 빼고 넘깁니다."""
    from dataclasses import dataclass

    from pipeline.alignment import supported_options

    @dataclass
    class Options:
        threshold: float = 0.5
        speech_pad_ms: int = 400

    wanted = {"speech_pad_ms": 0, "min_silence_duration_ms": 200}
    assert supported_options(Options, wanted) == {"speech_pad_ms": 0}


def test_supported_options_reads_a_plain_function_signature():
    from pipeline.alignment import supported_options

    def make(threshold: float = 0.5, min_silence_duration_ms: int = 2000):  # noqa: ARG001
        return None

    wanted = {"speech_pad_ms": 0, "min_silence_duration_ms": 200}
    assert supported_options(make, wanted) == {"min_silence_duration_ms": 200}


def test_supported_options_gives_up_when_the_signature_is_unreadable():
    """설정을 못 읽으면 아무것도 넘기지 않습니다. 잘못 넘기느니 기본값입니다."""
    from pipeline.alignment import supported_options

    assert supported_options(print, {"speech_pad_ms": 0}) == {}
