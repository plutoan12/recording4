"""용어집 보호: 번역기에 보내기 전 가리고, 받은 뒤 되돌리고, 새어 나온 것을 잡습니다."""

from __future__ import annotations

from pipeline.glossary import (
    apply_terms,
    missing_numbers,
    prompt_block,
    protect,
    restore,
    terms_in_text,
    violations,
)

ENTRIES = {"방탄소년단": "BTS", "Dynamite": None, "IU": None}


def test_terms_and_numbers_are_hidden_from_the_translator():
    protected = protect(["방탄소년단의 Dynamite는 2020년 8월 21일에 나왔다"], ENTRIES)
    hidden = protected.texts[0]
    assert "방탄소년단" not in hidden and "Dynamite" not in hidden and "2020" not in hidden
    assert set(protected.slots[0].values()) == {"BTS", "Dynamite", "2020", "8", "21"}


def test_restore_puts_the_target_rendering_back():
    protected = protect(["방탄소년단 3명"], ENTRIES)
    restored, lost = restore([protected.texts[0] + " came"], protected)
    assert restored == ["BTS 3명 came"] and lost == []


def test_a_lost_placeholder_is_reported_not_hidden():
    protected = protect(["방탄소년단"], ENTRIES)
    restored, lost = restore(["nothing left"], protected)
    assert restored == ["nothing left"] and lost == [0]


def test_latin_terms_match_whole_words_only():
    protected = protect(["IUS and IU"], ENTRIES)
    assert protected.texts[0] == "IUS and ⟦0⟧"


def test_number_sentinels_avoid_numbers_already_in_the_text():
    protected = protect(["9001번 버스 7대"], ENTRIES)
    assert "9001" in protected.slots[0].values()
    assert list(protected.slots[0]) != ["9001", "9002"] or protected.slots[0]["9002"] == "9001"


def test_longer_terms_win_over_their_substrings():
    protected = protect(["뉴진스 하니"], {"뉴진스 하니": "NewJeans Hanni", "뉴진스": "NewJeans"})
    assert protected.texts[0] == "⟦0⟧"


def test_only_terms_present_in_the_text_go_to_the_prompt():
    assert terms_in_text(ENTRIES, "방탄소년단 노래") == {"방탄소년단": "BTS"}
    assert "BTS" in prompt_block(terms_in_text(ENTRIES, "방탄소년단"))
    assert "STRICT" in prompt_block({"a": "b"}, strict=True)


def test_violations_and_leaks_are_caught_after_translation():
    assert violations("방탄소년단 2020", "Bangtan Boys 2020", ENTRIES) == {"방탄소년단": "BTS"}
    assert violations("방탄소년단", "bts sang", ENTRIES) == {}
    assert apply_terms("방탄소년단 sang", {"방탄소년단": "BTS"}) == "BTS sang"
    # 목표 표기 안에 원문 용어가 있으면 치환이 겹쳐 붙으므로 건너뜁니다.
    assert apply_terms("AI助手", {"AI": "AI助手"}) == "AI助手"
    assert missing_numbers("2020년 3명", "in 2020 people") == ["3"]
