import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from probe_voice_anchors import solo_spans, voice_check  # noqa: E402


def test_solo_union_does_not_duplicate_or_admit_other_voice():
    turns = [dict(start=0, end=2, speaker="a")] * 2 + [dict(start=1, end=3, speaker="b")]
    assert solo_spans(turns, 3) == {"a": [(0, 1)], "b": [(2, 3)]}


def test_nested_voice_has_no_clean_anchor():
    turns = [dict(start=0, end=3, speaker="a"), dict(start=1, end=2, speaker="b")]
    assert solo_spans(turns, 3)["b"] == []


def test_same_voice_contamination_cannot_pass_consistency_alone():
    assert voice_check(0.9, [0.89])["status"] == "rejected_acoustic_consistency"
    assert voice_check(0.9, [])["status"] == "insufficient_evidence"
    assert voice_check(0.8, [0.4])["status"] == "candidate_only"


def test_bad_times_rejected():
    with pytest.raises(ValueError):
        solo_spans([dict(start=0, end=float("nan"), speaker="a")], 3)
