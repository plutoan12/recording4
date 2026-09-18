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
