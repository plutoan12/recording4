import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "sortformer_evaluation",
    Path(__file__).resolve().parents[1] / "scripts/run_sortformer_evaluation.py",
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_preserve_overlap_and_empty_output():
    turns = module.parse_segments([["1 3 speaker_1", "0 2 speaker_0"]], 4)
    assert turns == [
        {"start": 0, "end": 2, "speaker": "speaker_0"},
        {"start": 1, "end": 3, "speaker": "speaker_1"},
    ]
    assert module.parse_segments([[]], 4) == []


@pytest.mark.parametrize(
    "result",
    [
        [],
        [["0 1 speaker_0"], []],
        ["0 1 speaker_0"],
        [["nan 2 speaker_0"]],
        [["0 inf speaker_0"]],
        [["0 5 speaker_0"]],
        [["-1 1 speaker_0"]],
        [["2 1 speaker_0"]],
        [["0 1 speaker_4"]],
        [["0 1"]],
        [["0 1 speaker_0 extra"]],
        [["abc 1 speaker_0"]],
        [[{"start": 0}]],
    ],
)
def test_do_not_silently_clip_or_accept_invalid_predictions(result):
    with pytest.raises(ValueError):
        module.parse_segments(result, 4)


def test_exact_end_boundary_is_valid():
    assert module.parse_segments([["0 4 speaker_0"]], 4)[0]["end"] == 4


def test_private_evidence_cannot_be_overwritten(tmp_path):
    path = tmp_path / "prediction.raw.json"
    module.write_private_json(path, {"raw": [["0 1 speaker_0"]]})
    before = path.read_bytes()
    assert path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        module.write_private_json(path, {"raw": []})
    assert path.read_bytes() == before
