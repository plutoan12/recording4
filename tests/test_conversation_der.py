import importlib.util
import sys
from pathlib import Path

import pytest

from test_conversation_evaluation import corpus  # noqa: F401

pytest.importorskip("pyannote.metrics")
scripts = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(scripts))
spec = importlib.util.spec_from_file_location(
    "conversation_der", scripts / "score_conversation_diarization.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def turn(start, end, speaker):
    return dict(start=start, end=end, speaker=speaker)


def test_perfect_renamed_labels_with_overlap():
    ref = [turn(0, 2, "a"), turn(1, 3, "b")]
    hyp = [turn(0, 2, "x"), turn(1, 3, "y")]
    result = module.score_segments(ref, hyp, 0, 4)
    assert result["total"] == 4
    assert result["diarization error rate"] == 0


def test_overlap_miss_and_silence_false_alarm_are_included():
    ref = [turn(0, 2, "a"), turn(1, 3, "b")]
    hyp = [turn(0, 2, "x"), turn(3, 4, "z")]
    result = module.score_segments(ref, hyp, 0, 4)
    assert result["missed detection"] == 2
    assert result["false alarm"] == 1
    assert result["diarization error rate"] == 0.75


def test_failed_empty_prediction_keeps_reference_denominator():
    result = module.score_segments([turn(0, 2, "a"), turn(1, 3, "b")], [], 0, 4)
    assert result["total"] == result["missed detection"] == 4
    assert result["diarization error rate"] == 1


def test_same_speaker_duplicate_tracks_do_not_inflate_denominator():
    ref = [turn(0, 2, "a"), turn(1, 3, "a")]
    result = module.score_segments(ref, [turn(0, 3, "x")], 0, 4)
    assert result["total"] == 3
    assert result["diarization error rate"] == 0


@pytest.mark.parametrize(
    "bad", [turn(-1, 1, "x"), turn(0, 5, "x"), turn(0, float("nan"), "x"), turn(0, 1, "")]
)
def test_invalid_predictions_are_not_clipped_or_dropped(bad):
    with pytest.raises(ValueError):
        module.score_segments([turn(0, 2, "a")], [bad], 0, 4)


def test_cohort_scoring_counts_failed_case_and_all_languages(corpus):  # noqa: F811
    import json

    from prepare_conversation_evaluation import prepare

    root, manifest = corpus
    lock = prepare(manifest, root)
    predictions = dict(
        schema=1,
        cohort_sha256=module.fingerprint(lock),
        model_revision="fixture-v1",
        cases=[
            dict(
                id=case["id"],
                audio_sha256=case["audio_sha256"],
                status="succeeded",
                turns=json.loads((root / case["reference"]).read_text())["segments"],
            )
            for case in manifest["cases"]
        ],
    )
    result = module.score(manifest, root, lock, predictions)
    assert result["total"]["diarization error rate"] == 0
    assert set(result["languages"]) == {"ko", "en", "ja", "zh"}
    assert "private text" not in json.dumps(result)
    predictions["cases"][0].update(status="failed", turns=[])
    result = module.score(manifest, root, lock, predictions)
    assert result["total"]["failed_cases"] == 1
    assert result["total"]["total"] == 12
    assert result["total"]["diarization error rate"] == 0.25
    assert not result["deploy_allowed"]
    predictions["cases"].pop()
    with pytest.raises(ValueError, match="missing"):
        module.score(manifest, root, lock, predictions)


def test_cli_scores_and_does_not_replace_previous_result(corpus):  # noqa: F811
    import json
    import subprocess

    from prepare_conversation_evaluation import prepare

    root, manifest = corpus
    lock = prepare(manifest, root)
    predictions = dict(
        schema=1,
        cohort_sha256=module.fingerprint(lock),
        model_revision="fixture-v1",
        cases=[
            dict(id=case["id"], audio_sha256=case["audio_sha256"], status="failed", turns=[])
            for case in manifest["cases"]
        ],
    )
    for name, value in (("manifest", manifest), ("lock", lock), ("predictions", predictions)):
        (root / f"{name}.json").write_text(json.dumps(value), encoding="utf-8")
    output = root / "der.json"
    command = [
        sys.executable,
        str(Path(module.__file__)),
        "--root",
        str(root),
        "--output",
        str(output),
    ]
    for name in ("manifest", "lock", "predictions"):
        command += [f"--{name}", str(root / f"{name}.json")]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    assert result.returncode == 2, result.stderr
    original = output.read_bytes()
    predictions["model_revision"] = "different"
    (root / "predictions.json").write_text(json.dumps(predictions), encoding="utf-8")
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert output.read_bytes() == original
