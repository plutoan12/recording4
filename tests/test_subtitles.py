"""자막 규칙. 순수 계산이라 외부 의존성 없이 검증합니다."""

from __future__ import annotations

import pytest

from pipeline.editing import Cue, Word
from pipeline.subtitles import (
    DEFAULT_RULES,
    LANGUAGE_RULES,
    SubtitleRules,
    apply_rules,
    check,
    normalize,
    pacing_rules,
    quality_report,
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


def test_splitting_a_cue_splits_its_word_times_too():
    from pipeline.editing import Word
    from pipeline.subtitles import words_for_chunks

    words = [
        Word(start=i, end=i + 0.5, text=t) for i, t in enumerate(["가나다", "라마바", "사아자"])
    ]
    assert words_for_chunks(words, ["가나다 라마바", "사아자"]) == [words[:2], words[2:]]
    # 단어가 조각 경계를 넘거나 글자가 다르면 모두 비웁니다.
    assert words_for_chunks(words, ["가나다 라", "마바 사아자"]) == [None, None]
    assert words_for_chunks(words, ["가나다 라마바", "사아차"]) == [None, None]
    assert words_for_chunks(None, ["가"]) == [None]
    cue = Cue(start=0, end=6, text="가나다 라마바 사아자", words=words)
    shaped = apply_rules([cue], NARROW)
    if len(shaped) > 1:
        assert all(part.words for part in shaped)
        assert [w.text for part in shaped for w in part.words] == ["가나다", "라마바", "사아자"]


def _spoken(start: float, words: list[tuple[str, float, float]]) -> Cue:
    """말한 시각이 붙은 자막 하나."""
    return Cue(
        start=start,
        end=words[-1][2] + 0.4,
        text=" ".join(w for w, _, _ in words),
        words=[Word(start=s, end=e, text=w) for w, s, e in words],
    )


SPEECH = [
    ("우리가", 0.0, 0.42),
    ("어제", 0.46, 0.78),
    ("말했던", 0.80, 1.22),
    ("그", 1.30, 1.42),
    ("영상", 1.45, 1.86),
    ("편집", 1.90, 2.30),
    ("진짜", 2.40, 2.78),
    ("잘", 2.80, 2.95),
    ("나왔어요.", 3.00, 3.62),
]


def test_pacing_picks_a_rule_set_and_leaves_the_default_alone():
    assert pacing_rules(None) == DEFAULT_RULES
    assert pacing_rules("broadcast", "ko") == DEFAULT_RULES
    assert pacing_rules("broadcast", "en") == LANGUAGE_RULES["en"]
    short = pacing_rules("shortform", "ko")
    assert short.max_lines == 1 and short.max_chars_per_line == 11 and short.use_word_timings
    assert pacing_rules("shortform", "en").max_chars_per_line == 14
    # 모르는 언어는 한국어 숏폼 값입니다.
    assert pacing_rules("shortform", "ja") == short
    with pytest.raises(ValueError, match="모르는 자막 끊기"):
        pacing_rules("tiktok")


def test_shortform_cuts_where_the_words_were_actually_spoken():
    shaped = apply_rules([_spoken(0.0, SPEECH)], pacing_rules("shortform", "ko"))
    assert [c.text for c in shaped] == ["우리가 어제 말했던", "그 영상 편집 진짜", "잘 나왔어요."]
    # 자막 시작은 그 말이 시작한 시각입니다.
    assert [round(c.start, 2) for c in shaped] == [0.0, 1.3, 2.8]
    # 끝은 다음 자막이 시작할 때까지 띄워 둡니다(깜빡이지 않게).
    assert [round(c.end, 2) for c in shaped] == [1.3, 2.8, 4.02]
    # 단어 시각은 조각마다 따라가므로 노래방·단어별 등장이 그대로 됩니다.
    assert [w.text for w in shaped[1].words] == ["그", "영상", "편집", "진짜"]
    # 줄바꿈 없이 한 줄입니다.
    assert all("\n" not in c.text for c in shaped)


def test_shortform_keeps_modifiers_with_the_word_they_modify():
    # "그"와 "잘"은 뒤 말을 꾸미므로 자막 끝에 혼자 남기지 않습니다.
    shaped = apply_rules([_spoken(0.0, SPEECH)], pacing_rules("shortform", "ko"))
    assert not any(c.text.endswith(("그", "잘")) for c in shaped)


def test_word_timings_are_ignored_unless_the_rules_ask_for_them():
    cue = _spoken(0.0, SPEECH)
    # 기본(방송) 규칙은 지금까지와 똑같이 글자 수로 나눕니다.
    assert len(apply_rules([cue], DEFAULT_RULES)) == 1
    # 사람이 글자를 고쳐 단어와 맞지 않으면 글자 수 방식으로 돌아갑니다.
    edited = cue.model_copy(update={"text": "우리가 어제 말했던 그 영상 편집 아주 잘 나왔어요."})
    shaped = apply_rules([edited], pacing_rules("shortform", "ko"))
    assert shaped[0].words is None
    # 단어가 하나뿐이어도 마찬가지입니다.
    one = _spoken(0.0, [("안녕하세요.", 0.0, 0.9)])
    assert len(apply_rules([one], pacing_rules("shortform", "ko"))) == 1


def test_shortform_never_runs_past_the_cue_it_came_from():
    cue = _spoken(10.0, [(w, s + 10, e + 10) for w, s, e in SPEECH])
    shaped = apply_rules([cue], pacing_rules("shortform", "ko"))
    assert shaped[0].start >= cue.start and shaped[-1].end <= cue.end
    assert all(
        later.start >= earlier.end for earlier, later in zip(shaped, shaped[1:], strict=False)
    )


def test_quality_report_shows_what_changed():
    cue = _spoken(0.0, SPEECH)
    broadcast = quality_report(apply_rules([cue], DEFAULT_RULES), DEFAULT_RULES)
    short_rules = pacing_rules("shortform", "ko")
    short = quality_report(apply_rules([cue], short_rules), short_rules)
    assert broadcast["count"] == 1 and short["count"] == 3
    # 숏폼은 자막이 짧아지고 장수가 늘어납니다.
    assert short["duration"]["median"] < broadcast["duration"]["median"]
    assert short["width"]["max"] < broadcast["width"]["max"]
    assert broadcast["violations"] == {} and short["violations"] == {}
    assert 0 <= short["coverage"] <= 1 and short["violation_ratio"] == 0.0
    # 자막이 없으면 0으로 채웁니다(나누기 오류를 내지 않습니다).
    empty = quality_report([], DEFAULT_RULES)
    assert empty["count"] == 0 and empty["duration"]["mean"] == 0.0


def test_worker_bakes_the_pacing_chosen_in_the_editor(tmp_path):
    import pysubs2

    from pipeline.editing import EditSpec
    from worker.rendering import write_subtitles

    cue = _spoken(10.0, [(w, s + 10, e + 10) for w, s, e in SPEECH])
    path = tmp_path / "captions.ass"
    write_subtitles(path, EditSpec(start=8, end=20, cues=[cue], caption_language="ko"))
    assert len([e for e in pysubs2.load(str(path)).events if e.style == "Default"]) == 1
    write_subtitles(
        path,
        EditSpec(start=8, end=20, cues=[cue], caption_language="ko", subtitle_pacing="shortform"),
    )
    events = [e for e in pysubs2.load(str(path)).events if e.style == "Default"]
    assert [e.plaintext for e in events] == [
        "우리가 어제 말했던",
        "그 영상 편집 진짜",
        "잘 나왔어요.",
    ]
    assert events[0].start == 2000
