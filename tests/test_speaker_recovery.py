from pipeline.alignment import WordTiming, squeeze
from pipeline.editing import Cue
from pipeline.speakers import SpeakerTurn, review_speakers
from worker.speaker_recovery import merge_agreed


def test_recovery_requires_independent_speaker_and_timing_agreement():
    cue = Cue(start=0, end=3, text="one two")
    blank = review_speakers([cue], [], [[]])[0]
    first = review_speakers(
        [cue], [SpeakerTurn(0, 3, "A")], [[WordTiming(0, 1, "one"), WordTiming(1, 2, "two")]]
    )[0]
    second = review_speakers(
        [cue], [SpeakerTurn(0, 3, "A")], [[WordTiming(0.1, 1.1, "one"), WordTiming(2, 3, "two")]]
    )[0]
    result = merge_agreed(blank, first, second)
    assert [w["speaker"] for w in result["words"]] == ["A", None]
    assert squeeze("".join(w["text"] for w in result["words"])) == squeeze(cue.text)
    assert result["needs_review"]
    second["words"][0]["speaker"] = "B"
    result = merge_agreed(blank, first, second)
    assert all(w["speaker"] is None for w in result["words"])


def test_recovery_never_replaces_existing_resolved_assignment():
    cue = Cue(start=0, end=1, text="one")
    first = review_speakers([cue], [SpeakerTurn(0, 1, "A")], [[WordTiming(0, 1, "one")]])[0]
    second = review_speakers([cue], [SpeakerTurn(0, 1, "B")], [[WordTiming(0, 1, "one")]])[0]
    result = merge_agreed(first, second, second)
    assert result["words"][0]["speaker"] == "A"
    assert first["words"][0]["speaker"] == "A"


def test_recovery_keeps_overlap_review_even_when_words_resolve():
    cue = Cue(start=0, end=1, text="one")
    base = review_speakers(
        [cue], [SpeakerTurn(0, 1, "A"), SpeakerTurn(0, 1, "B")], [[WordTiming(0, 1, "one")]]
    )[0]
    good = review_speakers([cue], [SpeakerTurn(0, 1, "A")], [[WordTiming(0, 1, "one")]])[0]
    result = merge_agreed(base, good, good)
    assert result["words"][0]["speaker"] == "A"
    assert result["needs_review"] and result["overlaps"]


def test_recovery_cannot_use_different_text_of_same_length():
    cue = Cue(start=0, end=1, text="one")
    base = review_speakers([cue], [], [[]])[0]
    wrong = review_speakers(
        [Cue(start=0, end=1, text="two")], [SpeakerTurn(0, 1, "A")], [[WordTiming(0, 1, "two")]]
    )[0]
    assert merge_agreed(base, wrong, wrong) == base
