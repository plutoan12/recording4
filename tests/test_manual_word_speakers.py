import sys
from pathlib import Path

import pytest

pytest.importorskip("pyannote.metrics")
root = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(root / "scripts"), str(root / "packages/pipeline")]
from score_manual_word_speakers import score, validate_reference  # noqa: E402


def word(a, b, s, text, clipped=False):
    return dict(start=a, end=b, speaker=s, text=text, boundary_clipped=clipped)


def test_renamed_ids_score_and_clipped_word_stays_in_denominator():
    words = [word(0, 1, "a", "hello"), word(1, 2, "b", "world", True)]
    turns = [dict(start=0, end=1, speaker="x"), dict(start=1, end=2, speaker="y")]
    result = score(words, turns, 2)
    assert (result["correct"], result["wrong"], result["unresolved"]) == (5, 0, 5)
    assert result["total_characters"] == 10
    assert result["boundary_unresolved_characters"] == 5
    assert result["asr_accuracy_measured"] is False


def test_no_speech_stays_unresolved_without_dropping_denominator():
    result = score([word(0, 1, "a", "abc")], [], 2)
    assert result["unresolved"] == result["total_characters"] == 3


def test_overlap_is_not_forced_to_single_speaker():
    result = score(
        [word(0, 1, "a", "abc")],
        [dict(start=0, end=1, speaker="x"), dict(start=0, end=1, speaker="y")],
        2,
    )
    assert result["unresolved"] == 3


def test_tiny_overlap_is_exposed_without_changing_primary_counts():
    words = [word(0, 1, "a", "abc")]
    turns = [dict(start=0, end=0.1, speaker="x")]
    result = score(words, turns, 2)
    assert result["correct"] == 3
    assert result["assigned_characters_below_80_percent_coverage"]["correct"] == 3
    doubled = score(words, turns + turns, 2)
    assert {k: doubled[k] for k in ("correct", "wrong", "unresolved")} == {
        k: result[k] for k in ("correct", "wrong", "unresolved")
    }
    assert (
        doubled["assigned_characters_below_80_percent_coverage"]
        == result["assigned_characters_below_80_percent_coverage"]
    )


def test_invalid_word_duration_rejected_before_diagnostic():
    with pytest.raises(ValueError):
        score([word(0, 0, "a", "abc")], [], 2)


def test_machine_or_wrong_window_reference_cannot_claim_manual_provenance():
    reference = dict(
        word_timing_source="human_manual_AMI",
        asr_evaluated=False,
        evaluation_start=0,
        evaluation_end=120,
        pilot_lock_sha256="a" * 64,
    )
    validate_reference(reference)
    for key, value in [
        ("word_timing_source", "whisper"),
        ("evaluation_end", 60),
        ("pilot_lock_sha256", None),
        ("asr_evaluated", True),
    ]:
        with pytest.raises(ValueError):
            validate_reference({**reference, key: value})
