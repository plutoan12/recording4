"""배경음 분리의 계산 부분과 합성 배선. 모델은 돌리지 않습니다.

실제 분리 품질은 `scripts/verify_separation.py`가 워커 이미지 안에서 잽니다.
여기서는 모델 없이도 틀릴 수 있는 것들을 봅니다: 구간을 나누다 소리를
흘리지 않는지, 목소리 갈래를 제대로 골라내는지, 그리고 배경음이 실제로
최종 오디오까지 도달하는지.
"""

from __future__ import annotations

import os
import shutil

import pytest

from worker.composition import dub_filter
from worker.separation import MissingDependency, background_sources, chunk_bounds


def test_chunks_cover_everything_without_a_hole() -> None:
    """구간을 나누다 한 칸이라도 빠지면 그 자리의 소리가 사라집니다."""
    total, rate = 44100 * 35, 44100
    covered = set()
    for start, end in chunk_bounds(total, rate):
        covered.update(range(start, end))
    assert covered == set(range(total))


def test_chunks_overlap_so_the_seam_does_not_click() -> None:
    """겹치지 않고 자르면 이은 자리에서 소리가 끊깁니다."""
    bounds = chunk_bounds(44100 * 35, 44100)
    assert len(bounds) > 1
    assert all(bounds[i + 1][0] < bounds[i][1] for i in range(len(bounds) - 1))


def test_a_short_sound_is_one_chunk() -> None:
    """짧은 소리를 굳이 나누면 경계만 늘어납니다."""
    assert chunk_bounds(44100 * 3, 44100) == [(0, 44100 * 3)]


def test_background_is_everything_but_the_voice() -> None:
    assert background_sources(["drums", "bass", "other", "vocals"]) == [0, 1, 2]


def test_a_model_with_only_voices_is_reported_not_silently_accepted() -> None:
    """목소리밖에 없으면 배경음은 무음입니다. 성공처럼 내보내면 안 됩니다."""
    with pytest.raises(MissingDependency):
        background_sources(["vocals"])


def test_the_mix_filter_does_not_quiet_the_dubbed_speech() -> None:
    """amix는 기본으로 입력 수만큼 음량을 나눕니다. 대사가 절반이 됩니다."""
    assert "normalize=0" in dub_filter(-9.0)
    assert "volume=-9.0dB" in dub_filter(-9.0)


def test_background_actually_reaches_the_final_audio(tmp_path) -> None:
    """섞었다고 적어 놓고 안 섞일 수 있습니다. 실제로 그려 보고 음량을 잽니다."""
    import subprocess

    from worker.composition import compose_dub, ffmpeg
    from worker.rendering import ffmpeg_binary

    if not os.environ.get("R4_FFMPEG_BINARY") and not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg가 없습니다.")

    source, speech, music = (tmp_path / n for n in ("src.mp4", "speech.wav", "music.wav"))
    ffmpeg(["-f", "lavfi", "-i", "color=c=blue:s=320x180:d=3", "-c:v", "libx264", str(source)])
    ffmpeg(["-f", "lavfi", "-i", "sine=frequency=300:duration=3", str(speech)])
    ffmpeg(["-f", "lavfi", "-i", "sine=frequency=900:duration=3", str(music)])

    def loudness(path) -> float:
        done = subprocess.run(
            [
                ffmpeg_binary(),
                "-nostdin",
                "-i",
                str(path),
                "-af",
                "volumedetect",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            timeout=300,
        )
        for line in done.stderr.decode("utf-8", "replace").splitlines():
            if "mean_volume:" in line:
                return float(line.split("mean_volume:")[1].split("dB")[0])
        raise AssertionError("volumedetect가 음량을 내놓지 않았습니다.")

    plain, mixed = tmp_path / "plain.mp4", tmp_path / "mixed.mp4"
    compose_dub(source, speech, plain, 0, 3)
    compose_dub(source, speech, mixed, 0, 3, background=music, background_gain_db=-3.0)
    # 배경음을 깔았으면 소리가 더 커집니다. 같으면 섞이지 않은 것입니다.
    assert loudness(mixed) > loudness(plain) + 0.5


def test_dubbing_still_runs_when_separation_is_unavailable(tmp_path, monkeypatch) -> None:
    """분리를 못 한다고 더빙 전체를 멈추면 안 됩니다. 배경음만 없으면 됩니다."""
    import worker.workflow_tasks as wf

    def unavailable(*args, **kwargs):
        raise MissingDependency("이 torchaudio에는 분리 번들이 없습니다.")

    monkeypatch.setattr(wf, "separate_background", unavailable)
    settings = type("S", (), {"whisper_device": "cpu"})()
    assert wf.separated_background(tmp_path / "src.mp4", tmp_path, settings) is None
