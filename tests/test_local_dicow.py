import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from score_local_dicow import evaluate  # noqa: E402


def slots():
    return [
        dict(
            model=m,
            window=i,
            reference=text,
            boundary_words=0,
            row_id=f"{m}-{i}" if not (m == "a" and i == 0) else None,
        )
        for m in ["a", "b"]
        for i, text in enumerate(["abc", ""])
    ]


def test_missing_speaker_and_hallucination_remain_in_score():
    rows = [
        dict(id="a-1", hypothesis="oops", generation_possibly_truncated=False),
        dict(id="b-0", hypothesis="abc", generation_possibly_truncated=False),
        dict(id="b-1", hypothesis="", generation_possibly_truncated=False),
    ]
    result = evaluate(slots(), rows)["models"]
    assert result["a"]["reference_characters"] == result["b"]["reference_characters"] == 3
    assert result["a"]["errors"] == 7
    assert result["a"]["missing_target_characters"] == 3
    assert result["a"]["empty_reference_insertions"] == 4
    assert result["b"]["errors"] == 0


def test_incomplete_run_is_not_scored_as_completed():
    with pytest.raises(ValueError, match="Incomplete"):
        evaluate(slots(), [])
