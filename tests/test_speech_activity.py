import importlib.util
import json
import subprocess
import sys
import wave
from pathlib import Path

import pytest

scripts = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(scripts))
spec = importlib.util.spec_from_file_location(
    "speech_activity", scripts / "score_speech_activity.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_scores_union_speech_without_counting_overlap_twice():
    result = module.score_activity([[0, 2], [1, 3]], [[0, 1], [2, 4]], 0, 4)
    assert result["reference_speech_seconds"] == 3
    assert result["matched_speech_seconds"] == 2
    assert result["miss_seconds"] == result["false_alarm_seconds"] == 1
    assert result["speech_error_seconds"] == 2


def test_empty_prediction_keeps_reference_denominator():
    result = module.score_activity([[1, 3]], [], 0, 4)
    assert result["miss_seconds"] == result["reference_speech_seconds"] == 2
    assert result["precision"] == 0


@pytest.mark.parametrize(
    "bad",
    [
        [[-1, 1]],
        [[0, 5]],
        [[1, 1]],
        [[0, float("nan")]],
        [[True, 1]],
        [[0, 1, 2]],
    ],
)
def test_rejects_invalid_intervals(bad):
    with pytest.raises(ValueError):
        module.score_activity([[0, 1]], bad, 0, 4)


def test_input_order_does_not_change_union_metric():
    result = module.score_activity([[2, 3], [0, 1]], [[2, 3], [0, 1]], 0, 4)
    assert result["speech_error_seconds"] == 0
    assert result["reference_speech_seconds"] == 2


def test_cli_binds_prediction_to_audio_and_preserves_output(tmp_path):
    audio = tmp_path / "audio.wav"
    with wave.open(str(audio), "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(16000)
        target.writeframes(b"\0\0" * 32000)
    reference = tmp_path / "reference.json"
    reference.write_text(
        json.dumps(
            {
                "schema": 1,
                "source_sha256": module.sha256(audio),
                "speech_presence_complete": True,
                "annotated_interval": [0, 2],
                "provenance": "fixed human reference",
                "turns": [{"start": 0.5, "end": 1.5, "speaker": "human"}],
            }
        ),
        encoding="utf-8",
    )
    prediction = tmp_path / "prediction.json"
    prediction.write_text(
        json.dumps(
            {
                "schema": 1,
                "source_sha256": module.sha256(audio),
                "model_revision": "fixed",
                "timestamps": [[0.5, 1.5]],
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "score.json"
    command = [
        sys.executable,
        str(Path(module.__file__)),
        "--audio",
        str(audio),
        "--reference",
        str(reference),
        "--prediction",
        str(prediction),
        "--output",
        str(output),
        "--evaluation-end",
        "2",
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    scored = json.loads(output.read_text())
    assert scored["schema"] == 2
    assert scored["reference_speech_presence_complete"] is True
    assert scored["reference_annotated_interval"] == [0, 2]
    assert scored["reference_provenance"] == "fixed human reference"
    original = output.read_bytes()
    payload = json.loads(prediction.read_text())
    payload["timestamps"] = []
    prediction.write_text(json.dumps(payload), encoding="utf-8")
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert output.read_bytes() == original


def test_rejects_reference_without_complete_speech_presence(tmp_path):
    audio = tmp_path / "audio.wav"
    with wave.open(str(audio), "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(16000)
        target.writeframes(b"\0\0" * 32000)
    prediction = {
        "schema": 1,
        "source_sha256": module.sha256(audio),
        "model_revision": "fixed",
        "timestamps": [[0.5, 1.5]],
    }
    reference = {
        "schema": 1,
        "source_sha256": module.sha256(audio),
        "speech_presence_complete": False,
        "annotated_interval": [0, 2],
        "provenance": "partial annotation",
        "turns": [{"start": 0.5, "end": 1.5, "speaker": "human"}],
    }
    with pytest.raises(ValueError, match="does not cover all speech"):
        module.score(
            audio,
            reference,
            prediction,
            2,
            reference_sha256="reference",
            prediction_sha256="prediction",
        )


@pytest.mark.parametrize(
    "change",
    [
        lambda reference: reference.clear(),
        lambda reference: reference.pop("schema"),
        lambda reference: reference.update(source_sha256="different"),
        lambda reference: reference.update(annotated_interval=[0, 1.5]),
        lambda reference: reference.update(annotated_interval=[False, 2]),
        lambda reference: reference.update(provenance=""),
        lambda reference: reference.update(turns="invalid"),
    ],
)
def test_rejects_unbound_or_incomplete_reference_metadata(tmp_path, change):
    audio = tmp_path / "audio.wav"
    with wave.open(str(audio), "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(16000)
        target.writeframes(b"\0\0" * 32000)
    audio_sha = module.sha256(audio)
    reference = {
        "schema": 1,
        "source_sha256": audio_sha,
        "speech_presence_complete": True,
        "annotated_interval": [0, 2],
        "provenance": "fixed human reference",
        "turns": [{"start": 0.5, "end": 1.5, "speaker": "human"}],
    }
    change(reference)
    prediction = {
        "schema": 1,
        "source_sha256": audio_sha,
        "model_revision": "fixed",
        "timestamps": [[0.5, 1.5]],
    }
    with pytest.raises((ValueError, KeyError)):
        module.score(
            audio,
            reference,
            prediction,
            2,
            reference_sha256="reference",
            prediction_sha256="prediction",
        )


def test_rejects_legacy_bare_reference_without_traceback(tmp_path):
    audio = tmp_path / "audio.wav"
    with wave.open(str(audio), "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(16000)
        target.writeframes(b"\0\0" * 32000)
    reference = tmp_path / "reference.json"
    reference.write_text(
        json.dumps([{"start": 0.5, "end": 1.5, "speaker": "human"}]), encoding="utf-8"
    )
    prediction = tmp_path / "prediction.json"
    prediction.write_text(
        json.dumps(
            {
                "schema": 1,
                "source_sha256": module.sha256(audio),
                "model_revision": "fixed",
                "timestamps": [[0.5, 1.5]],
            }
        ),
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            sys.executable,
            str(Path(module.__file__)),
            "--audio",
            str(audio),
            "--reference",
            str(reference),
            "--prediction",
            str(prediction),
            "--output",
            str(tmp_path / "score.json"),
            "--evaluation-end",
            "2",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize("prediction", [[], "invalid", None])
def test_rejects_non_object_prediction(tmp_path, prediction):
    audio = tmp_path / "audio.wav"
    with wave.open(str(audio), "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(16000)
        target.writeframes(b"\0\0" * 32000)
    reference = {
        "schema": 1,
        "source_sha256": module.sha256(audio),
        "speech_presence_complete": True,
        "annotated_interval": [0, 2],
        "provenance": "fixed human reference",
        "turns": [{"start": 0.5, "end": 1.5, "speaker": "human"}],
    }
    with pytest.raises(ValueError, match="Invalid prediction"):
        module.score(
            audio,
            reference,
            prediction,
            2,
            reference_sha256="reference",
            prediction_sha256="prediction",
        )


def test_cli_sanitizes_overflowing_reference_number(tmp_path):
    audio = tmp_path / "audio.wav"
    with wave.open(str(audio), "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(16000)
        target.writeframes(b"\0\0" * 32000)
    reference = tmp_path / "reference.json"
    reference.write_text(
        json.dumps(
            {
                "schema": 1,
                "source_sha256": module.sha256(audio),
                "speech_presence_complete": True,
                "annotated_interval": [0, 10**400],
                "provenance": "fixed human reference",
                "turns": [{"start": 0.5, "end": 1.5, "speaker": "human"}],
            }
        ),
        encoding="utf-8",
    )
    prediction = tmp_path / "prediction.json"
    prediction.write_text(
        json.dumps(
            {
                "schema": 1,
                "source_sha256": module.sha256(audio),
                "model_revision": "fixed",
                "timestamps": [[0.5, 1.5]],
            }
        ),
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            sys.executable,
            str(Path(module.__file__)),
            "--audio",
            str(audio),
            "--reference",
            str(reference),
            "--prediction",
            str(prediction),
            "--output",
            str(tmp_path / "score.json"),
            "--evaluation-end",
            "2",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert result.stderr == "Invalid speech-activity inputs or output.\n"
