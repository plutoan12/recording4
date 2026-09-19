"""자막 규칙. 순수 계산이라 외부 의존성 없이 검증합니다."""

from __future__ import annotations

import pytest

from pipeline.editing import Cue
from pipeline.subtitles import (
    DEFAULT_RULES,
    SubtitleRules,
    apply_rules,
    check,
    normalize,
    split_text,
    text_width,
    wrap_text,
)

NARROW = SubtitleRules(max_chars_per_line=10, max_lines=2, min_duration=1.0)


def test_rules_reject_impossible_values() -> None:
    with pytest.raises(ValueError):
        SubtitleRules(max_chars_per_line=0)
    with pytest.raises(ValueError):
        SubtitleRules(max_cps=0)


def test_width_counts_latin_and_spaces_as_half() -> None:
    """Netflix 한국어 지침의 계산 방식입니다. 한글 1자, 라틴·공백·문장부호 0.5자."""
    assert text_width("가나다") == 3.0
    assert text_width("abc") == 1.5
    assert text_width("가 나") == 2.5
    assert text_width("가나다, hello!") == 7.0


def test_wrap_breaks_at_word_boundaries() -> None:
    assert wrap_text("가나다 라마바 사아자 차카타", NARROW) == ["가나다 라마바 사아자", "차카타"]


def test_wrap_keeps_one_line_while_it_fits() -> None:
    """공백이 0.5자이므로 한글 9자+공백 2개는 10자 폭에 들어갑니다."""
    assert wrap_text("가나다 라마바 사아자", NARROW) == ["가나다 라마바 사아자"]


def test_wrap_fits_more_latin_than_hangul_per_line() -> None:
    assert wrap_text("abcdefghijklmnopqrst", NARROW) == ["abcdefghijklmnopqrst"]
    assert len(wrap_text("가" * 20, NARROW)) == 2


def test_wrap_hard_splits_token_longer_than_line() -> None:
    """공백이 없는 언어에서도 글자를 잃지 않습니다."""
    lines = wrap_text("가" * 25, NARROW)
    assert lines == ["가" * 10, "가" * 10, "가" * 5]
    assert "".join(lines) == "가" * 25


def test_wrap_does_not_enforce_line_count() -> None:
    """줄 수 제한은 check가 보고합니다. 여기서 글자를 버리지 않습니다."""
    assert len(wrap_text("가나다 " * 20, NARROW)) > NARROW.max_lines


def test_normalize_collapses_whitespace() -> None:
    assert normalize("  가나\n\n다  라  ") == "가나 다 라"


def test_split_prefers_sentence_boundaries() -> None:
    parts = split_text("첫 문장입니다. 두 번째 문장입니다.", 2)
    assert parts == ["첫 문장입니다.", "두 번째 문장입니다."]


def test_split_falls_back_to_words_then_characters() -> None:
    assert split_text("가나 다라 마바 사아", 2) == ["가나 다라", "마바 사아"]
    assert split_text("가" * 9, 3) == ["가가가", "가가가", "가가가"]


def test_split_never_returns_empty_parts() -> None:
    for parts in range(1, 6):
        assert all(split_text("가나 다라 마바", parts))


def test_long_cue_is_split_with_proportional_timing() -> None:
    cue = Cue(start=0, end=8, text="가나다 라마바 사아자 차카타 파하가 나다라 마바사 아자차")
    shaped = apply_rules([cue], NARROW)
    assert len(shaped) > 1
    assert shaped[0].start == 0
    assert shaped[-1].end == 8
    # 글자를 잃지 않습니다.
    assert "".join(c.text for c in shaped).replace("\n", "").replace(" ", "") == cue.text.replace(
        " ", ""
    )


def test_split_cues_do_not_overlap_and_stay_ordered() -> None:
    cue = Cue(start=2, end=10, text="가나다 라마바 사아자 차카타 파하가 나다라 마바사 아자차")
    shaped = apply_rules([cue], NARROW)
    for earlier, later in zip(shaped, shaped[1:], strict=False):
        assert earlier.end == later.start
        assert earlier.end > earlier.start


def test_cue_is_not_split_when_there_is_no_time() -> None:
    """읽을 수 없이 짧은 자막을 만드는 대신 그대로 두고 보고합니다."""
    cue = Cue(start=0, end=1.2, text="가나다 라마바 사아자 차카타 파하가 나다라 마바사 아자차")
    shaped = apply_rules([cue], NARROW)
    assert len(shaped) == 1
    assert shaped[0].start == 0 and shaped[0].end == 1.2
    assert any(v.kind == "cps" for v in check(shaped, NARROW))


def test_short_cue_is_only_wrapped() -> None:
    shaped = apply_rules([Cue(start=0, end=3, text="가나다 라마바")], NARROW)
    assert len(shaped) == 1
    assert shaped[0].text == "가나다 라마바"


def test_check_reports_reading_speed() -> None:
    # 두 줄(폭 32)에는 들어가지만 1초에 30자는 기본 한도 12자/초를 넘습니다.
    fast = [Cue(start=0, end=1, text="가" * 30)]
    assert [v.kind for v in check(fast, DEFAULT_RULES)] == ["cps"]


def test_default_rules_follow_the_korean_guide() -> None:
    """근거는 Netflix 한국어 지침 I부입니다. SDH 상향값(14자/초)은 쓰지 않습니다."""
    assert DEFAULT_RULES.max_chars_per_line == 16
    assert DEFAULT_RULES.max_lines == 2
    assert DEFAULT_RULES.max_cps == 12.0
    assert DEFAULT_RULES.max_duration == 7.0
    assert DEFAULT_RULES.min_duration >= 5 / 6


def test_check_reports_line_overflow() -> None:
    """두 줄에 담기지 않는 자막을 보고합니다. 폭 32자를 넘으면 세 줄이 됩니다."""
    assert [v.kind for v in check([Cue(start=0, end=5, text="가" * 33)], DEFAULT_RULES)] == [
        "lines"
    ]


def test_check_reports_duration_bounds() -> None:
    assert any(v.kind == "duration" for v in check([Cue(start=0, end=0.3, text="가")], NARROW))
    assert any(v.kind == "duration" for v in check([Cue(start=0, end=30, text="가")], NARROW))


def test_check_reports_overlap() -> None:
    cues = [Cue(start=0, end=3, text="가"), Cue(start=2, end=5, text="나")]
    assert any(v.kind == "overlap" for v in check(cues, NARROW))


def test_shaped_cues_pass_their_own_line_rule_when_time_allows() -> None:
    cue = Cue(
        start=0, end=20, text="가나다 라마바 사아자 차카타 파하가 나다라 마바사 아자차 카타파"
    )
    assert not [v for v in check(apply_rules([cue], NARROW), NARROW) if v.kind == "lines"]


def test_write_subtitles_applies_rules_to_the_ass_file(tmp_path) -> None:  # noqa: ANN001
    """렌더 경로가 실제로 규칙을 적용하는지 ASS 파일로 확인합니다. FFmpeg는 필요 없습니다."""
    from types import SimpleNamespace

    from worker.rendering import write_subtitles

    spec = SimpleNamespace(
        width=1080,
        height=1920,
        start=0,
        end=12,
        title="",
        font_size=64,
        cues=[Cue(start=0, end=12, text="가나다 라마바 사아자 차카타 파하가 나다라 마바사 아자차")],
    )
    path = tmp_path / "captions.ass"
    write_subtitles(path, spec, NARROW)
    body = path.read_text(encoding="utf-8")
    events = [line for line in body.splitlines() if line.startswith("Dialogue:")]

    # 자막 하나가 여러 개로 나뉘고, 줄바꿈이 ASS 개행(\N)으로 들어갑니다.
    assert len(events) > 1
    assert any(r"\N" in line for line in events)
    # libass 자동 줄바꿈에 맡기지 않으므로 원문이 통째로 들어가지 않습니다.
    assert "가나다 라마바 사아자 차카타 파하가 나다라 마바사 아자차" not in body


def test_english_rules_use_the_measured_line_length() -> None:
    """지침 줄당 42자는 가로 화면 기준입니다. 세로 숏폼에 들어가는지는 CI가
    렌더해서 확인하고(scripts/measure_subtitles.py), 여기서는 그 값이 코드에
    그대로 박혀 있는지만 봅니다.

    한국어 숫자를 그대로 쓰면 영어 줄이 32자에서 잘리고 읽기 속도는 24자/초까지
    봐줍니다. 그래서 언어별 값이 필요합니다."""
    from pipeline.subtitles import rules_for, text_width

    rules = rules_for("en")
    assert text_width("M" * 38) == rules.max_chars_per_line
    assert text_width("a" * 20) == rules.max_cps


def test_korean_stays_on_the_korean_guideline() -> None:
    from pipeline.subtitles import DEFAULT_RULES, rules_for

    assert rules_for("ko") == DEFAULT_RULES
    assert rules_for(None) == DEFAULT_RULES


def test_a_region_tag_still_finds_the_language() -> None:
    from pipeline.subtitles import rules_for

    assert rules_for("en-US") == rules_for("en")


def test_an_unknown_language_keeps_what_it_was_given() -> None:
    """모르는 언어를 추측해서 바꾸지 않습니다."""
    from pipeline.subtitles import DEFAULT_RULES, rules_for

    assert rules_for("fr") == DEFAULT_RULES


def test_a_setting_the_person_changed_wins_over_the_language_default() -> None:
    """설정을 바꾼 것은 사람의 결정입니다. 언어가 덮어쓰지 않습니다."""
    from pipeline.subtitles import SubtitleRules, rules_for

    chosen = SubtitleRules(max_chars_per_line=10, max_cps=5.0)
    assert rules_for("en", chosen) == chosen


def test_protect_numeric_units_and_japanese_endings():
    for text, protected in [
        ("明天凌晨2点，价格将从10美元变为12美元。", "12美元"),
        ("明日の午前2時に、価格が10ドルから12ドルに変更されます。", "から"),
        ("The price changes from $10 to $12 at 2 AM tomorrow.", "2 AM"),
    ]:
        assert protected in "\n".join(wrap_text(text))
        assert "".join(wrap_text(text)).replace(" ", "") == text.replace(" ", "")


def test_time_expression_survives_cue_splitting():
    parts = split_text("The price will change tomorrow at 2 AM and remain unchanged afterwards", 3)
    assert "2 AM" in "\n".join(parts)
