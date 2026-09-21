"""번역 QA는 보고만 합니다. 무엇을 잡는지와 무엇을 잡지 않는지를 고정합니다."""

from __future__ import annotations

from pipeline.translation_qa import grouped, review


def kinds(issues):
    return [(i.index, i.kind) for i in issues]


def test_reports_glossary_numbers_untranslated_and_empty():
    issues = review(
        ["방탄소년단 3명", "안녕", "잘 가"],
        ["Bangtan boys", "안녕", ""],
        source="ko",
        target="en",
        entries={"방탄소년단": "BTS"},
    )
    assert kinds(issues) == [(0, "glossary"), (0, "number"), (1, "untranslated"), (2, "empty")]


def test_source_script_left_in_the_translation_is_flagged_except_glossary_targets():
    issues = review(
        ["아이유가 노래했다", "오늘"], ["아이유 sang", "today"], source="ko", target="en"
    )
    assert kinds(issues) == [(0, "script")]
    # 용어집이 그렇게 쓰라고 한 표기는 출발 언어 글자여도 문제가 아닙니다.
    assert (
        review(["아이유"], ["아이유 sang"], source="ko", target="en", entries={"아이유": "아이유"})
        == []
    )


def test_same_language_and_unknown_source_skip_the_language_checks():
    assert review(["안녕"], ["안녕"], source="ko", target="ko") == []
    assert kinds(review(["안녕"], ["안녕"], source=None, target="en")) == [(0, "untranslated")]


def test_subtitle_rules_use_the_source_timing_and_target_language():
    long_english = "word " * 40
    issues = review(["짧은 원문"], [long_english], source="ko", target="en", timings=[(0.0, 1.0)])
    assert {i.kind for i in issues} == {"lines", "cps"}
    assert review(["짧은 원문"], ["short"], source="ko", target="en", timings=[(0.0, 2.0)]) == []


def test_grouped_shape_matches_the_workflow_data():
    issues = review(["3명"], ["people"], source="ko", target="en")
    assert grouped(issues) == [{"index": 0, "issues": ["숫자 누락: 3"]}]
