import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from probe_consensus_speech_gaps import consensus_gaps  # noqa: E402


def test_keeps_only_shared_speech_not_covered_by_guarded_words():
    words = [dict(start=1, end=2, text="known", timing_valid=True)]
    first = [dict(start=0, end=4, speaker="a")]
    second = [dict(start=0.5, end=3.5, speaker="b")]
    assert consensus_gaps(words, [first, second], 4) == [(2.1, 3.5)]


def test_invalid_word_timing_is_not_used_to_erase_candidate_time():
    words = [dict(start=0, end=4, text="uncertain", timing_valid=False)]
    turns = [dict(start=0, end=1, speaker="a")]
    assert consensus_gaps(words, [turns, turns], 4) == [(0, 1)]


def test_rejects_invalid_policy():
    with pytest.raises(ValueError, match="gap policy"):
        consensus_gaps([], [[], []], 4, minimum=0)
