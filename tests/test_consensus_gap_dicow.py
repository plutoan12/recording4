import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from prepare_consensus_gap_dicow import build_manifest  # noqa: E402


def test_builds_every_predicted_target_without_reference_text():
    gaps = {"audit": [dict(id="gap-0", start=4, end=5)]}
    prediction = {
        "turns": [
            dict(start=0, end=6, speaker="b"),
            dict(start=1, end=2, speaker="a"),
        ]
    }
    rows = build_manifest(gaps, prediction, "/data/en.wav", duration=10)
    assert [row["target"] for row in rows] == ["a", "b"]
    assert all((row["start"], row["end"], row["reference"]) == (1, 8, "") for row in rows)
    assert all((row["core_start"], row["core_end"]) == (4, 5) for row in rows)
    assert all(row["reference"] == "" for row in rows)


def test_rejects_duplicate_gap_ids():
    gaps = {"audit": [dict(id="same", start=1, end=2), dict(id="same", start=3, end=4)]}
    prediction = {"turns": [dict(start=0, end=5, speaker="a")]}
    with pytest.raises(ValueError, match="duplicate gap"):
        build_manifest(gaps, prediction, "/data/en.wav", duration=5)
