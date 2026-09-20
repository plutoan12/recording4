import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from score_consensus_gap_reference import coverage  # noqa: E402


def test_counts_boundary_overlap_separately_from_midpoint_words():
    gaps = [dict(id="gap", start=1, end=2)]
    words = [
        dict(start=0.8, end=1.1, text="edge"),
        dict(start=1.2, end=1.6, text="core"),
        dict(start=2, end=2.2, text="outside"),
    ]
    assert coverage(gaps, words) == [
        dict(
            id="gap",
            duration=1,
            overlap_words=2,
            midpoint_words=1,
            overlap_characters=8,
        )
    ]
