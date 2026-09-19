import importlib.util
from pathlib import Path

import pytest

from pipeline.editing import Cue


@pytest.fixture
def matrix():
    spec = importlib.util.spec_from_file_location(
        "r4matrix", Path(__file__).parents[1] / "scripts/verify_sync_matrix.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_matrix_detects_end_truncation(matrix, monkeypatch):
    original = [Cue(start=1, end=20, text="long")]
    monkeypatch.setattr(
        matrix,
        "sync_subtitles",
        lambda *a: ([Cue(start=1, end=11, text="long")], {"offset_seconds": 0}),
    )
    assert not matrix.evaluate(Path("unused"), original, 0, 0.5)["pass"]


def test_matrix_does_not_call_rejection_a_pass(matrix, monkeypatch):
    def reject(*args):
        raise ValueError("bad match")

    monkeypatch.setattr(matrix, "sync_subtitles", reject)
    result = matrix.evaluate(Path("unused"), [Cue(start=1, end=2, text="test")], 0, 0.5)
    assert not result["pass"] and result["rejected"] == "bad match"


@pytest.mark.parametrize("error,passed", [(0.5, True), (0.5001, False)])
def test_matrix_keeps_half_second_limit(matrix, monkeypatch, error, passed):
    original = [Cue(start=1, end=2, text="test")]
    monkeypatch.setattr(
        matrix,
        "sync_subtitles",
        lambda *a: ([Cue(start=1 + error, end=2 + error, text="test")], {"offset_seconds": error}),
    )
    assert matrix.evaluate(Path("unused"), original, 0, 0.5)["pass"] is passed
