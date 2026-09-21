"""문맥 배치와 어색한 번역 고르기. 외부 호출 없이 계산만 봅니다."""

from __future__ import annotations

import pytest

from pipeline.subtitles import text_width
from pipeline.translation_context import ends_sentence, groups, join, split_across
from pipeline.translation_review import Finding, pick, review, review_limit


def test_fragments_are_grouped_until_a_sentence_ends():
    texts = ["그래서 저는", "어제 그 자료를", "다시 만들었습니다.", "오늘은 쉽니다."]
    assert groups(texts) == [[0, 1, 2], [3]]


def test_complete_sentences_are_never_merged():
    """문장부호가 다 있는 대본은 지금까지와 똑같이 한 줄씩 번역됩니다."""
    texts = ["첫 문장입니다.", "둘째 문장입니다.", "셋째 문장입니다."]
    assert groups(texts) == [[0], [1], [2]]


def test_a_long_run_is_cut_at_the_limit():
    """문장부호가 아예 없어도 묶음이 무한정 커지지 않습니다."""
    assert groups(["조각"] * 14) == [[0, 1, 2, 3, 4, 5], [6, 7, 8, 9, 10, 11], [12, 13]]


@pytest.mark.parametrize(
    ("text", "expected"),
    [("끝났습니다.", True), ('"끝났습니다."', True), ("이어집니다", False), ("쉼표,", False)],
)
def test_sentence_end_allows_a_closing_quote(text, expected):
    assert ends_sentence(text) is expected


def test_join_uses_no_space_for_languages_that_have_none():
    assert join(["그래서 저는", "왔습니다."], "ko") == "그래서 저는 왔습니다."
    assert join(["昨日は", "来ました。"], "ja") == "昨日は来ました。"


def test_split_follows_how_long_each_cue_was_on_screen():
    """가운데 자막이 가장 길었으므로 가장 넓은 몫을 받습니다."""
    pieces = split_across("So I rebuilt that material again yesterday.", [1.0, 2.0, 1.0], "en")
    assert pieces == ["So I rebuilt", "that material again", "yesterday."]
    # 낱말을 잃지 않습니다. 가운데 자막이 두 배 길었으므로 가장 넓은 몫을 받습니다.
    assert " ".join(pieces) == "So I rebuilt that material again yesterday."
    assert text_width(pieces[1]) > text_width(pieces[0]) + text_width(pieces[2]) - 3


def test_split_never_returns_an_empty_piece():
    pieces = split_across("one two three", [1, 1, 1], "en")
    assert pieces == ["one", "two", "three"]


def test_split_gives_up_rather_than_cutting_a_word_in_half():
    """낱말이 모자라면 글자로 쪼개지 않고 포기합니다(조각별 번역으로 복귀)."""
    assert split_across("Short.", [1, 1, 1], "en") is None


def test_languages_without_spaces_split_by_character():
    pieces = split_across("私は昨日その資料を作り直しました。", [1, 1], "ja")
    assert pieces == ["私は昨日その資料を", "作り直しました。"]
    assert "".join(pieces) == "私は昨日その資料を作り直しました。"


def test_nothing_to_split():
    assert split_across("", [1], "en") is None
    assert split_across("hello", [], "en") is None


def test_review_flags_untranslated_and_empty_and_repeated():
    findings = review(
        [
            ("안녕하세요 반갑습니다", "안녕하세요 반갑습니다"),
            ("오늘 날씨가 좋습니다", ""),
            ("계속 이야기합니다", "and and and so on"),
            ("자료를 다시 만들었습니다", "I rebuilt the material."),
        ]
    )
    flagged = {finding.index for finding in findings}
    assert flagged == {0, 1, 2}


def test_review_uses_the_batch_median_not_a_fixed_ratio():
    """언어쌍마다 늘어나는 비율이 달라 이 묶음 자체의 중앙값에서 잡습니다."""
    normal = [("원문입니다 그렇습니다.", "This is the source text, yes indeed.")] * 5
    short = [("원문입니다 그렇습니다.", "Yes.")]
    findings = review(normal + short)
    assert [finding.index for finding in findings] == [5]
    assert "짧습니다" in findings[0].reasons[0]


def test_missing_glossary_terms_are_a_reason_to_look_again():
    findings = review(
        [("녹화4로 편집했습니다.", "It was edited with Recording Four.")],
        missing_terms={0: ["Recording 4"]},
    )
    assert findings and "Recording 4" in findings[0].reasons[0]


def test_a_grouped_fragment_is_not_suspected_of_missing_context():
    pairs = [("그래서 저는", "So I")]
    alone = review(pairs)[0]
    together = review(pairs, grouped=[0])[0]
    assert any("문맥 없이" in reason for reason in alone.reasons)
    assert not any("문맥 없이" in reason for reason in together.reasons)
    assert together.score < alone.score


def test_the_number_of_retranslated_cues_is_capped():
    """비용이 번역량에 비례해 뛰지 않도록 상한을 둡니다."""
    assert review_limit(0) == 0
    assert review_limit(1) == 1
    assert review_limit(30) == 9  # 30%
    assert review_limit(1000) == 20  # 상한
    findings = [Finding(index=index, score=1.0) for index in range(10)]
    assert pick(findings, 10) == [0, 1, 2]
