import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from align_dicow_context import select_core  # noqa: E402


def w(a, b, text):
    return dict(start=a, end=b, text=text)


def test_context_not_reinserted_and_split_tokens_match():
    left = [w(0, 1, "intro"), w(1, 2, "can't"), w(2, 3, "outro")]
    right = [w(0, 1, "intro"), w(1, 1.5, "can"), w(1.5, 2, "'t"), w(2, 3, "outro")]
    assert select_core("intro can't outro", left, right, 1, 2, 0, 3) == (
        "can't",
        "timing_consensus_only",
    )


def test_only_disputed_core_word_rejects_when_nothing_else_agrees():
    assert select_core("hi", [w(0, 1, "hi")], [w(1, 2, "hi")], 0, 1, 0, 3)[0] is None
    assert select_core("hi", [w(0, 1, "hi")], [], 0, 1, 0, 3)[0] is None


def test_timing_disagreement_is_not_hidden_by_same_text():
    assert select_core("hi", [w(0, 1, "hi")], [w(0.6, 1.6, "hi")], 0, 2, 0, 3)[0] is None


def test_disputed_boundary_word_does_not_discard_independent_consensus():
    left = [w(0, 1, "context"), w(1, 1.4, "keep"), w(1.4, 2.4, "edge")]
    right = [w(0, 1, "context"), w(1.05, 1.45, "keep"), w(2.1, 2.4, "edge")]
    assert select_core("context keep edge", left, right, 1, 2, 0, 3) == (
        "keep",
        "partial_timing_consensus",
    )


def test_expansion_preserves_cores_and_source_items():
    from prepare_dicow_context import expand

    items = [dict(id="a", start=1, end=2), dict(id="b", start=118, end=120)]
    result = expand(items)
    assert [(r["core_start"], r["core_end"]) for r in result] == [(1, 2), (118, 120)]
    assert [(r["start"], r["end"]) for r in result] == [(0, 5), (115, 120)]
    assert items[0]["start"] == 1
