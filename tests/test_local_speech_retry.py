import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from run_local_speech_retry import retry_regions, splice  # noqa: E402


def test_selects_only_alternate_only_speech_and_merges_padding():
    baseline = [dict(start=1, end=2), dict(start=3, end=4)]
    alternate = [dict(start=0, end=5)] * 2
    assert retry_regions(baseline, alternate, 5) == ([[0, 1], [2, 3], [4, 5]], [[0, 5]])


def test_padding_never_duplicates_or_replaces_outside_words():
    original = [dict(start=0, end=1, text="keep"), dict(start=1, end=2, text="old")]
    retries = [dict(start=0, end=1, text="context"), dict(start=1, end=2, text="new")]
    assert [w["text"] for w in splice(original, retries, [[1, 2]])] == ["keep", "new"]
    assert [w["text"] for w in splice(original, [], [[1, 2]])] == ["keep"]


def test_no_disagreement_needs_no_crops():
    turns = [dict(start=0, end=2)]
    assert retry_regions(turns, turns, 2) == ([], [])


def test_invalid_times_fail_before_inference():
    with pytest.raises(ValueError):
        retry_regions([], [dict(start=-1, end=2)], 2)


def test_invalid_baseline_timing_text_is_preserved():
    original = [dict(start=1, end=1, text="keep", timing_valid=False)]
    assert splice(original, [], [[0, 2]]) == original


def test_scoring_normalization_keeps_lexical_characters():
    from score_local_speech_retry import normalize

    assert normalize("That's A_B!") == "thatsab"
    assert normalize("한글 日本語 中文") == "한글日本語中文"
