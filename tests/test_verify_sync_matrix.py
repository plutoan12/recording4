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


def test_matrix_measures_word_alignment_on_the_same_conditions(matrix, monkeypatch):
    """같은 조건에서 두 방법을 나란히 재야 어느 쪽이 나은지 말할 수 있습니다."""
    original = [Cue(start=1, end=2, text="test"), Cue(start=5, end=6, text="또")]
    monkeypatch.setattr(
        matrix,
        "realign_subtitles",
        lambda *a, **k: (
            [Cue(start=c.start, end=c.end, text=c.text) for c in original],
            {"method": "align", "max_shift_seconds": -2.5},
        ),
    )
    found = matrix.evaluate(Path("unused"), original, 2.5, 0.5, "align")
    assert found["pass"] and found["max_shift_seconds"] == -2.5
    # align은 이동값이 자막마다 다릅니다. shift처럼 이동값 하나로 판정하지 않습니다.
    assert "offset_seconds" not in found


def test_matrix_does_not_pass_word_alignment_that_misses(matrix, monkeypatch):
    original = [Cue(start=1, end=2, text="test")]
    monkeypatch.setattr(
        matrix,
        "realign_subtitles",
        lambda *a, **k: (
            [Cue(start=1.6, end=2.6, text="test")],
            {"method": "align", "max_shift_seconds": 0.6},
        ),
    )
    assert not matrix.evaluate(Path("unused"), original, 0, 0.5, "align")["pass"]
