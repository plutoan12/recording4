import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from prepare_additive_retry import proposals  # noqa: E402


def test_existing_word_is_preserved_and_only_gap_proposed():
    base = [dict(start=0, end=1, text="old")]
    before = copy.deepcopy(base)
    items = [dict(id="x", target="a", core_start=0, core_end=3)]
    aligned = dict(
        rows=[dict(id="x", hypothesis="old new")],
        audit=[
            dict(
                id="x",
                status="timing_consensus_only",
                fallback=False,
                left=[dict(start=0, end=1, text="old"), dict(start=2, end=3, text="new")],
            )
        ],
    )
    result = proposals(base, items, aligned)
    assert result[0]["words"] == [dict(start=2, end=3, text="new")]
    assert base == before


def test_failed_alignment_never_proposes_words():
    assert (
        proposals(
            [], [], dict(rows=[], audit=[dict(id="x", status="alignment_failed", fallback=True)])
        )
        == []
    )


def test_additions_never_edit_or_reorder_baseline_and_collision_fails():
    import pytest
    from verify_additive_voice import append_preserving_baseline

    base = [dict(start=0, end=1, text="keep"), dict(start=2, end=3, text="also")]
    before = copy.deepcopy(base)
    result = append_preserving_baseline(base, [dict(start=1, end=2, text="new")])
    assert [w for w in result if not w.get("added")] == base == before
    with pytest.raises(ValueError):
        append_preserving_baseline(base, [dict(start=0.5, end=1.5, text="collision")])


def test_voice_match_alone_cannot_approve_and_nan_is_rejected():
    from verify_additive_voice import reasons

    assert reasons("candidate_only", 0.8, 0.2, "yes", "no", 1) == ["independent_asr_disagrees"]
    assert "insufficient_voice_match" in reasons(
        "candidate_only", float("nan"), 0.2, "yes", "yes", 1
    )
    assert reasons("candidate_only", 0.8, 0.2, "yes", "yes", 1) == []


def test_uncertain_zero_length_existing_word_blocks_same_time_addition():
    import pytest
    from verify_additive_voice import append_preserving_baseline

    with pytest.raises(ValueError):
        append_preserving_baseline(
            [dict(start=1, end=1, text="keep")], [dict(start=0.5, end=1.5, text="new")]
        )
