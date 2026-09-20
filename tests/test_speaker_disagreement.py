import copy

import pytest

from pipeline.speaker_disagreement import compare_turns, mark_reviews, overlap_retry_windows


def turn(a, b, speaker):
    return dict(start=a, end=b, speaker=speaker)


def test_renamed_speakers_and_duplicate_tracks_are_not_disagreement():
    base = [turn(0, 2, "a"), turn(2, 4, "b")]
    candidate = [turn(0, 2, "y"), turn(0, 1, "y"), turn(2, 4, "x")]
    assert compare_turns(base, candidate, 4)["intervals"] == []


def test_missed_speech_is_review_not_an_automatic_repair():
    result = compare_turns([turn(0, 3, "a")], [turn(0, 1, "x")], 4)
    assert result["intervals"] == [
        dict(start=1, end=3, reasons=["baseline_only_speech"], overlap_suspected=False)
    ]
    assert not result["automatic_reassignment"]
    assert overlap_retry_windows(result, 4) == []


def test_overlap_disagreement_is_selected_for_retry():
    result = compare_turns([turn(0, 5, "a")], [turn(0, 5, "x"), turn(2, 3, "y")], 5)
    assert result["intervals"][0]["start"] == 2
    assert result["intervals"][0]["end"] == 3
    assert "speaker_count_disagreement" in result["intervals"][0]["reasons"]
    assert overlap_retry_windows(result, 5)[0] == dict(
        start=1.5, end=3.5, needs_review=True, automatic_reassignment=False
    )


def test_tied_correspondence_is_not_presented_as_agreement():
    result = compare_turns([turn(0, 2, "a"), turn(2, 4, "b")], [turn(0, 4, "x")], 4)
    assert all("uncertain_speaker_correspondence" in r["reasons"] for r in result["intervals"])


def test_review_flags_preserve_original_assignments_and_old_flags():
    cue = dict(
        start=0,
        end=3,
        text="a b",
        speaker="old",
        needs_review=False,
        words=[
            dict(start=0, end=1, text="a", speaker="old", needs_review=True),
            dict(start=2, end=3, text="b", speaker="old", needs_review=False),
        ],
    )
    original = copy.deepcopy(cue)
    result = compare_turns([turn(0, 3, "a")], [turn(0, 2, "x")], 3)
    marked = mark_reviews([cue], result)[0]
    assert cue == original
    assert marked["needs_review"]
    assert all(w["needs_review"] for w in marked["words"])
    assert [w["speaker"] for w in marked["words"]] == ["old", "old"]
    assert marked["text"] == original["text"]


@pytest.mark.parametrize("a,b", [(0, float("nan")), (-1, 2), (0, 5), (True, 2), (2, 1)])
def test_invalid_bounds_are_not_clipped(a, b):
    with pytest.raises(ValueError):
        compare_turns([turn(a, b, "x")], [], 4)


def test_long_overlap_is_split_without_discarding_duration():
    result = compare_turns([turn(0, 70, "a")], [turn(0, 70, "x"), turn(0, 70, "y")], 70)
    windows = overlap_retry_windows(result, 70)
    assert [(w["start"], w["end"]) for w in windows] == [(0, 30), (30, 60), (60, 70)]


def test_recomparison_clears_old_reasons_but_keeps_review_flag():
    row = dict(start=0, end=1, needs_review=True, model_disagreement_reasons=["old"])
    marked = mark_reviews([row], dict(intervals=[]))[0]
    assert marked["needs_review"]
    assert "model_disagreement_reasons" not in marked
    assert row["model_disagreement_reasons"] == ["old"]


def test_review_artifact_must_match_audio():
    from compare_diarizer_reviews import compare

    artifact = dict(source_sha256="a" * 64, turns=[turn(0, 1, "a")])
    with pytest.raises(ValueError, match="Reviews"):
        compare(artifact, artifact, dict(source_sha256="b" * 64, reviews=[]), 2)
    result = compare(artifact, artifact, dict(source_sha256="a" * 64, reviews=[]), 2)
    assert result["reviews"] == []
    with pytest.raises(ValueError, match="duration"):
        compare(artifact, artifact, dict(source_sha256="a" * 64, reviews=[], duration_seconds=3), 2)
