import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def evidence():
    active = {
        "schema": 1,
        "source_video_sha256": "v" * 64,
        "source_audio_sha256": "a" * 64,
        "model_revision": "visual-v1",
        "score_kind": "class_1_logit",
        "active_threshold": 0,
        "frame_rate": 2,
        "frame_count": 10,
        "tracks": [
            {"frames": list(range(10)), "scores": [1] * 10},
            {"frames": [4, 5, 6], "scores": [1, 1]},
        ],
    }
    diarization = {
        "schema": 1,
        "source_sha256": "a" * 64,
        "model_revision": "audio-v1",
        "turns": [
            {"start": 0, "end": 5, "speaker": "speaker_0"},
            {"start": 2, "end": 3.5, "speaker": "speaker_1"},
        ],
    }
    return active, diarization


def test_disagreement_preserves_unknown_frames_and_lower_bounds(evidence, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    from compare_active_speaker_diarization import compare

    result = compare(*evidence, active_sha256="x" * 64, diarization_sha256="y" * 64)
    assert result["visual_active_seconds_lower_bound"] == 5
    assert result["visual_overlap_seconds_lower_bound"] == 1
    assert result["audio_overlap_seconds"] == 1.5
    assert result["overlap_agreement_seconds_lower_bound"] == 1
    assert result["visual_unknown_frames"] == 1
    assert result["visual_unknown_seconds"] == 0.5
    assert result["unscored_track_frames"] == 1
    assert result["visual_overlap_supported_by_audio_fraction"] == 1
    assert result["audio_overlap_supported_by_visual_fraction_lower_bound"] == pytest.approx(2 / 3)
    assert result["accuracy_claim_allowed"] is False
    assert result["deploy_allowed"] is False
    assert result["review_intervals"]["visual_overlap_without_audio_overlap"] == [
        {"start": 2.0, "end": 2.5}
    ]


def test_same_speaker_chunks_and_turn_boundaries_do_not_create_overlap(evidence, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    from compare_active_speaker_diarization import compare

    active, audio = copy.deepcopy(evidence)
    audio["turns"] = [
        {"start": 0, "end": 2.25, "speaker": "speaker_0"},
        {"start": 1.75, "end": 2.25, "speaker": "speaker_0"},
        {"start": 2.25, "end": 5, "speaker": "speaker_1"},
    ]
    result = compare(active, audio, active_sha256="x", diarization_sha256="y")
    assert result["audio_speech_seconds"] == 5
    assert result["audio_overlap_seconds"] == 0
    assert result["audio_overlap_supported_by_visual_fraction_lower_bound"] is None


def test_empty_visual_overlap_fraction_is_unknown(evidence, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    from compare_active_speaker_diarization import compare

    active, audio = copy.deepcopy(evidence)
    active["tracks"] = active["tracks"][:1]
    result = compare(active, audio, active_sha256="x", diarization_sha256="y")
    assert result["visual_overlap_supported_by_audio_fraction"] is None


@pytest.mark.parametrize(
    "change",
    [
        lambda active, _audio: active.update(score_kind="probability"),
        lambda active, _audio: active["tracks"][0].update(scores=[1] * 11),
        lambda active, _audio: active["tracks"][0].update(frames=[0, 0]),
        lambda _active, audio: audio.update(source_sha256="different"),
        lambda _active, audio: audio["turns"][0].update(end=5.1),
    ],
)
def test_invalid_or_mismatched_evidence_is_rejected(evidence, change, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    from compare_active_speaker_diarization import compare

    active, audio = copy.deepcopy(evidence)
    change(active, audio)
    with pytest.raises(ValueError):
        compare(active, audio, active_sha256="x", diarization_sha256="y")


def test_cli_preserves_existing_output(evidence, tmp_path):
    active, audio = evidence
    active_path, audio_path, output = (
        tmp_path / "active.json",
        tmp_path / "audio.json",
        tmp_path / "output.json",
    )
    active_path.write_text(json.dumps(active), encoding="utf-8")
    audio_path.write_text(json.dumps(audio), encoding="utf-8")
    script = Path(__file__).resolve().parents[1] / "scripts/compare_active_speaker_diarization.py"
    command = [
        sys.executable,
        str(script),
        "--active",
        str(active_path),
        "--diarization",
        str(audio_path),
        "--output",
        str(output),
    ]
    assert subprocess.run(command, check=False).returncode == 0
    assert subprocess.run(command, check=False).returncode == 0
    output.write_text("{}", encoding="utf-8")
    assert subprocess.run(command, check=False).returncode == 1
