"""Actual FFmpeg render, decoding and audio-level checks; no external media."""

import os
import shutil
import subprocess

import pytest

from pipeline.editing import Cue, EditSpec, ReframeSettings, TrimSettings
from worker.rendering import render_clip


@pytest.mark.parametrize("mode", ["pad", "crop"])
def test_real_render(tmp_path, mode):
    binary = os.environ.get("R4_FFMPEG_BINARY") or shutil.which("ffmpeg")
    if not binary:
        pytest.skip("FFmpeg required; CI installs it")
    source = tmp_path / "source.mp4"
    subprocess.run(
        [
            binary,
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=320x240:rate=24",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000",
            "-t",
            "4",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            str(source),
        ],
        check=True,
    )
    output = tmp_path / "out.mp4"
    render_clip(
        source,
        output,
        EditSpec(
            start=1,
            end=3,
            width=180,
            height=320,
            mode=mode,
            title="Title",
            font_size=20,
            cues=[Cue(start=0.5, end=2, text="hello")],
        ),
    )
    assert output.stat().st_size > 1000
    decoded = subprocess.run(
        [binary, "-i", str(output), "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "180x320" in decoded.stderr
    assert "00:00:02." in decoded.stderr
    assert "mean_volume:" in decoded.stderr and "mean_volume: -inf" not in decoded.stderr


def _probe_seconds(binary: str, path) -> float:
    """실제 길이(초). ffprobe는 FFmpeg와 함께 설치됩니다."""
    probe = shutil.which("ffprobe") or binary.replace("ffmpeg", "ffprobe")
    result = subprocess.run(
        [probe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(result.stdout.strip())


def test_real_render_cuts_the_silent_parts(tmp_path):
    """무음 컷은 필터 문자열이 맞아야 돌아갑니다. 실제로 렌더해서 길이를 잽니다.

    발화 구간은 직접 넣습니다. 여기서 보는 것은 **자르는 쪽**이지 찾는 쪽이
    아닙니다(찾는 쪽은 worker.analysis에 따로 있습니다).
    """
    binary = os.environ.get("R4_FFMPEG_BINARY") or shutil.which("ffmpeg")
    if not binary:
        pytest.skip("FFmpeg required; CI installs it")
    source = tmp_path / "source.mp4"
    subprocess.run(
        [
            binary,
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=320x240:rate=24",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000",
            "-t",
            "9",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            str(source),
        ],
        check=True,
    )
    plain, trimmed = tmp_path / "plain.mp4", tmp_path / "trimmed.mp4"
    spec = EditSpec(
        start=0,
        end=9,
        width=180,
        height=320,
        cues=[Cue(start=3.2, end=4.8, text="남는 말"), Cue(start=6.5, end=7.0, text="잘리는 말")],
    )
    render_clip(source, plain, spec)
    # 3~5초만 말이 있다고 알려 줍니다. 나머지는 잘려야 합니다.
    render_clip(
        source,
        trimmed,
        spec.model_copy(update={"silence": TrimSettings(pad=0.1)}),
        speech=[(3.0, 5.0)],
    )
    whole = _probe_seconds(binary, plain)
    cut = _probe_seconds(binary, trimmed)
    assert whole == pytest.approx(9.0, abs=0.5)
    # 남길 토막은 2.9~5.1초, 곧 2.2초입니다.
    assert cut == pytest.approx(2.2, abs=0.4), f"자른 뒤 {cut:.2f}초 (원본 {whole:.2f}초)"


def test_real_render_follows_a_moving_centre_and_denoises(tmp_path):
    """crop 식과 음성 필터가 실제로 FFmpeg를 통과하는지 봅니다.

    얼굴 위치는 직접 넣습니다. 여기서 보는 것은 **따라가는 쪽**이지 찾는 쪽이
    아닙니다(찾는 쪽은 worker.analysis.face_track 에 따로 있습니다).
    """
    binary = os.environ.get("R4_FFMPEG_BINARY") or shutil.which("ffmpeg")
    if not binary:
        pytest.skip("FFmpeg required; CI installs it")
    source = tmp_path / "source.mp4"
    subprocess.run(
        [
            binary,
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=640x360:rate=24",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000",
            "-t",
            "4",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            str(source),
        ],
        check=True,
    )
    output = tmp_path / "out.mp4"
    render_clip(
        source,
        output,
        EditSpec(
            start=0,
            end=4,
            mode="crop",
            width=180,
            height=320,
            denoise="soft",
            reframe=ReframeSettings(),
            cues=[Cue(start=0.5, end=2.0, text="따라가기")],
        ),
        # 왼쪽에서 오른쪽으로 옮겨 갑니다.
        faces=[(0.0, 0.2), (1.0, 0.4), (2.0, 0.6), (3.0, 0.8)],
    )
    assert output.stat().st_size > 1000
    assert _probe_seconds(binary, output) == pytest.approx(4.0, abs=0.5)
