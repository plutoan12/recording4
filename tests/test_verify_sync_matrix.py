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


def test_matrix_splits_start_and_end_errors(matrix, monkeypatch):
    """합쳐 놓으면 어디가 어긋났는지 안 보입니다.

    끝 시각의 정답은 에너지 문턱이라 말끝 숨소리·잔향만큼 늦습니다. 길이를
    그대로 옮기는 방법은 그 정답과 저절로 맞고, 음성에서 끝을 다시 찾는
    방법은 벌을 받습니다. 나눠 놓아야 그 편향이 보입니다.
    """
    original = [Cue(start=1, end=5, text="test")]
    monkeypatch.setattr(
        matrix,
        "sync_subtitles",
        # 시작은 맞고 끝만 1.4초 이릅니다.
        lambda *a: ([Cue(start=1, end=3.6, text="test")], {"offset_seconds": 0}),
    )
    found = matrix.evaluate(Path("unused"), original, 0, 0.5)
    assert found["max_start_error_seconds"] == 0.0
    assert found["max_end_error_seconds"] == 1.4
    assert not found["pass"]
