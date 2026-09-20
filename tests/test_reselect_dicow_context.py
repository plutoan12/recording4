import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from reselect_dicow_context import reselect  # noqa: E402


def row(row_id, hypothesis, truncated=False):
    return dict(
        id=row_id,
        hypothesis=hypothesis,
        generation_possibly_truncated=truncated,
        errors=3,
        cer=1,
        reference_characters=3,
    )


def item(row_id):
    return dict(id=row_id, start=0, end=3, core_start=1, core_end=2)


def test_reselect_preserves_partial_consensus_and_removes_stale_scores():
    items = [item("x")]
    rows = [row("x", "context keep edge")]
    baseline = [row("x", "")]
    aligned = dict(
        audit=[
            dict(
                id="x",
                left=[
                    dict(start=0, end=1, text="context"),
                    dict(start=1, end=1.4, text="keep"),
                    dict(start=1.4, end=2.4, text="edge"),
                ],
                right=[
                    dict(start=0, end=1, text="context"),
                    dict(start=1.05, end=1.45, text="keep"),
                    dict(start=2.1, end=2.4, text="edge"),
                ],
            )
        ]
    )
    output, audit = reselect(items, rows, baseline, aligned)
    assert output[0]["hypothesis"] == "keep"
    assert output[0]["context_alignment_status"] == "partial_timing_consensus"
    assert "cer" not in output[0]
    assert not audit[0]["fallback"]
    assert audit[0]["selected"] == [dict(start=1, end=1.4, text="keep")]


def test_reselect_rejects_missing_or_duplicate_rows():
    with pytest.raises(ValueError, match="Missing or duplicate"):
        reselect([item("x")], [row("x", "a")], [row("x", "")], dict(audit=[]))
