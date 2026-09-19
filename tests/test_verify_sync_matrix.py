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


def test_matrix_reads_several_drift_values(matrix):
    """어긋남을 여러 값으로 재야 어디서 뒤집히는지 보입니다."""
    import argparse

    parser = argparse.ArgumentParser()
    assert matrix.drifts("0,0.15,0.3", parser) == (0.0, 0.15, 0.3)
    # 비우면 어긋남 없음입니다. 예전처럼 한 덩어리 어긋남만 재는 자리입니다.
    assert matrix.drifts("", parser) == (0.0,)


def test_matrix_refuses_a_drift_that_is_not_a_number(matrix):
    import argparse

    parser = argparse.ArgumentParser()
    for bad in ("0.1,여보세요", "-0.2"):
        with pytest.raises(SystemExit):
            matrix.drifts(bad, parser)


def test_matrix_table_keeps_each_drift_on_its_own_row(matrix, capsys):
    """값마다 줄을 나눠야 합니다. 묶으면 가장 나쁜 값만 남아 뒤집힘이 사라집니다."""
    results = [
        {
            "variant": "music_intro",
            "duration_seconds": 100.0,
            "cue_count": 9,
            "cases": {
                matrix.case_key("shift", 0.0, 0.0): {
                    "pass": True,
                    "max_start_error_seconds": 0.04,
                    "max_end_error_seconds": 0.04,
                },
                matrix.case_key("shift", 0.0, 0.6): {
                    "pass": False,
                    "max_start_error_seconds": 2.4,
                    "max_end_error_seconds": 2.4,
                },
                matrix.case_key("align", 0.0, 0.0): {
                    "pass": False,
                    "max_start_error_seconds": 1.0,
                    "max_end_error_seconds": 1.0,
                },
                matrix.case_key("align", 0.0, 0.6): {
                    "pass": False,
                    "max_start_error_seconds": 1.0,
                    "max_end_error_seconds": 1.0,
                },
            },
        }
    ]
    matrix.summarize(results, ("shift", "align"), (0.0, 0.6))
    rows = [line for line in capsys.readouterr().out.splitlines() if "music_intro" in line]
    assert len(rows) == 2
    # 어긋남이 없으면 shift가 낫고, 크면 뒤집힙니다. 그게 줄마다 보여야 합니다.
    assert "0.040" in rows[0] and "1.000" in rows[0]
    assert "2.400" in rows[1] and "1.000" in rows[1]


def test_matrix_reports_which_sample_it_measured(matrix, tmp_path):
    """표에는 표본 id가 붙어야 합니다. 없으면 다른 음성의 숫자와 섞입니다."""
    import json

    (tmp_path / "expected.json").write_text(
        json.dumps({"gap": 1.0, "sentences": [], "sample_id": "abc123def456"})
    )
    assert matrix.sample_name(tmp_path) == "abc123def456"


def test_matrix_says_so_when_the_sample_id_is_missing(matrix, tmp_path):
    import json

    (tmp_path / "expected.json").write_text(json.dumps({"gap": 1.0, "sentences": []}))
    # 없는 것을 있는 척하면 안 됩니다. 옛 폴더에는 id가 없습니다.
    assert matrix.sample_name(tmp_path) == "알 수 없음"


def test_matrix_separates_the_first_cue_error(matrix, monkeypatch):
    """오차가 첫 자막에만 몰렸는지 보이려면 첫 자막을 뺀 값도 있어야 합니다."""
    truth = [Cue(start=1, end=3, text="하나"), Cue(start=5, end=7, text="둘")]
    monkeypatch.setattr(
        matrix,
        "realign_subtitles",
        lambda *a, **k: (
            [Cue(start=1.8, end=3.8, text="하나"), Cue(start=5.05, end=7.05, text="둘")],
            {"max_shift_seconds": 0.8},
        ),
    )
    found = matrix.evaluate(Path("unused"), truth, 0.0, 0.5, "align")
    assert found["max_start_error_seconds"] == 0.8
    # 첫 자막만 0.8초 늦고 둘째는 0.05초입니다. 최댓값 하나로는 안 보입니다.
    assert found["max_start_error_after_first_seconds"] == 0.05


def test_matrix_leaves_the_first_cue_column_empty_for_one_cue(matrix, monkeypatch):
    truth = [Cue(start=1, end=3, text="하나")]
    monkeypatch.setattr(
        matrix,
        "realign_subtitles",
        lambda *a, **k: ([Cue(start=1.8, end=3.8, text="하나")], {"max_shift_seconds": 0.8}),
    )
    # 자막이 하나면 뺄 것이 없습니다. 0으로 적으면 잘 맞은 것처럼 보입니다.
    assert (
        matrix.evaluate(Path("unused"), truth, 0.0, 0.5, "align")[
            "max_start_error_after_first_seconds"
        ]
        is None
    )
