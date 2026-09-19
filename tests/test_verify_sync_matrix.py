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


def test_matrix_measures_alignment_without_the_vad_snap(matrix, monkeypatch):
    """align_nosnap은 스냅을 끈 정렬입니다. 같은 조건에서 함께 재야 폭이 보입니다."""
    seen: dict = {}

    def fake(source, cues, **kwargs):
        seen.update(kwargs)
        return list(cues), {"method": "align", "max_shift_seconds": 0.0}

    monkeypatch.setattr(matrix, "realign_subtitles", fake)
    original = [Cue(start=1, end=2, text="test")]
    matrix.evaluate(Path("unused"), original, 0, 0.5, "align")
    assert seen["snap"] is True
    matrix.evaluate(Path("unused"), original, 0, 0.5, "align_nosnap")
    assert seen["snap"] is False


def test_matrix_can_make_each_cue_drift_further(matrix, monkeypatch):
    """자막마다 어긋남이 커지는 모양. 이동값 하나로는 못 고칩니다.

    강제 정렬을 제안한 이유가 이것인데, 지금까지 잰 열 조건에는 한 번도
    나오지 않았습니다. 전부 전체가 한 덩어리로 어긋난 경우였습니다.
    """
    seen: list = []
    monkeypatch.setattr(
        matrix,
        "sync_subtitles",
        lambda source, cues: (seen.extend(cues), (list(cues), {"offset_seconds": 0}))[1],
    )
    truth = [
        Cue(start=1, end=2, text="하나"),
        Cue(start=5, end=6, text="둘"),
        Cue(start=9, end=10, text="셋"),
    ]
    matrix.evaluate(Path("unused"), truth, 0.0, 0.5, "shift", drift=0.4)
    # 첫 자막은 그대로, 다음부터 0.4초씩 더 밀립니다.
    assert [round(c.start, 3) for c in seen] == [1.0, 5.4, 9.8]


def test_matrix_does_not_judge_a_drifting_case_by_one_offset(matrix, monkeypatch):
    """어긋남이 자막마다 다르면 '맞는 이동값' 자체가 없습니다."""
    truth = [Cue(start=1, end=2, text="하나"), Cue(start=5, end=6, text="둘")]
    monkeypatch.setattr(
        matrix,
        "sync_subtitles",
        # 시각은 정답과 같게 돌려주지만 이동값은 엉뚱하게 보고합니다.
        lambda source, cues: (
            [Cue(start=c.start, end=c.end, text=c.text) for c in truth],
            {"offset_seconds": 9.9},
        ),
    )
    assert matrix.evaluate(Path("unused"), truth, 0.0, 0.5, "shift", drift=0.4)["pass"]
    # 어긋남이 한 덩어리일 때는 이동값도 판정에 넣습니다.
    assert not matrix.evaluate(Path("unused"), truth, 0.0, 0.5, "shift", drift=0.0)["pass"]


def test_matrix_gate_none_judges_nothing(matrix):
    """재기만 하고 판정하지 않는 자리가 있습니다. 빈 문자열이 아니라 none입니다."""
    import argparse

    parser = argparse.ArgumentParser()
    assert matrix.pick("none", parser) == ()
    # 빈 값은 기본값(shift)으로 떨어집니다. 판정을 끄려면 none을 써야 합니다.
    assert matrix.pick("", parser) == ("shift",)
