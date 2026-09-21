"""Actual FFmpeg render, decoding and audio-level checks; no external media."""

import os
import shutil
import subprocess
import uuid

import pytest

from pipeline.editing import Cue, EditSpec
from worker.rendering import RenderError, render_clip, render_preview


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


def ffmpeg_or_skip() -> str:
    binary = os.environ.get("R4_FFMPEG_BINARY") or shutil.which("ffmpeg")
    if not binary:
        pytest.skip("FFmpeg required; CI installs it")
    return binary


def make_source(binary: str, path, seconds: int, *, audio: bool = True) -> None:
    command = [binary, "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=24"]
    if audio:
        command += ["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000"]
    command += ["-t", str(seconds), "-c:v", "libx264"]
    if audio:
        command += ["-c:a", "aac"]
    subprocess.run([*command, str(path)], check=True)


def probe_value(path, stream: str, entry: str) -> str:
    binary = os.environ.get("R4_FFPROBE_BINARY") or shutil.which("ffprobe")
    if not binary:
        pytest.skip("ffprobe required; CI installs it")
    out = subprocess.run(
        [binary, "-v", "error", "-select_streams", stream, "-show_entries", entry,
         "-of", "default=nw=1:nk=1", str(path)],
        check=True, capture_output=True, text=True,
    )  # fmt: skip
    return out.stdout.strip().splitlines()[0]


def test_real_render_joins_segments_and_applies_speed(tmp_path):
    """여러 구간을 이어 붙이고 배속을 걸면 결과 길이가 그만큼 됩니다."""
    binary = ffmpeg_or_skip()
    source = tmp_path / "source.mp4"
    make_source(binary, source, 12)
    output = tmp_path / "joined.mp4"
    spec = EditSpec(
        start=0,
        end=12,
        segments=[{"start": 0, "end": 2}, {"start": 8, "end": 12, "speed": 2.0}],
        cues=[Cue(start=0.5, end=1.5, text="앞"), Cue(start=9, end=11, text="뒤")],
    )
    assert spec.output_seconds == 4.0
    render_clip(source, output, spec, has_audio=True)
    assert abs(float(probe_value(output, "v:0", "format=duration")) - 4.0) < 0.4
    # 소리도 함께 이어 붙습니다. 트랙이 사라지면 더빙·게시가 망가집니다.
    assert probe_value(output, "a:0", "stream=codec_type") == "audio"


def test_real_render_mixes_background_music_and_fades(tmp_path):
    binary = ffmpeg_or_skip()
    source, music = tmp_path / "source.mp4", tmp_path / "music.m4a"
    make_source(binary, source, 6)
    subprocess.run(
        [binary, "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=220",
         "-t", "2", "-c:a", "aac", str(music)],
        check=True,
    )  # fmt: skip
    output = tmp_path / "with-music.mp4"
    spec = EditSpec(
        start=0, end=6, fade_in=0.5, fade_out=0.5, music_asset_id=uuid.uuid4(), music_gain_db=-12
    )
    # 음악이 2초뿐이라 되풀이해서 6초를 채웁니다.
    render_clip(source, output, spec, music=music, has_audio=True)
    assert abs(float(probe_value(output, "v:0", "format=duration")) - 6.0) < 0.4
    assert probe_value(output, "a:0", "stream=codec_type") == "audio"


def test_real_render_keeps_going_when_the_source_has_no_audio(tmp_path):
    binary = ffmpeg_or_skip()
    source = tmp_path / "silent.mp4"
    make_source(binary, source, 6, audio=False)
    output = tmp_path / "out.mp4"
    spec = EditSpec(start=0, end=6, segments=[{"start": 0, "end": 2}, {"start": 4, "end": 6}])
    render_clip(source, output, spec, has_audio=False)
    assert abs(float(probe_value(output, "v:0", "format=duration")) - 4.0) < 0.4


def test_real_preview_makes_one_frame_at_the_output_size(tmp_path):
    binary = ffmpeg_or_skip()
    source = tmp_path / "source.mp4"
    make_source(binary, source, 12)
    output = tmp_path / "preview.png"
    spec = EditSpec(
        start=0,
        end=12,
        segments=[{"start": 0, "end": 2}, {"start": 8, "end": 12}],
        cues=[Cue(start=2.5, end=3.5, text="뒤 구간 자막")],
    )
    # 결과 3초는 원본 9초입니다. 그 자리의 자막이 그려집니다.
    render_preview(source, output, spec, 3.0)
    assert output.exists() and output.stat().st_size > 0
    assert probe_value(output, "v:0", "stream=width") == "1080"
    assert probe_value(output, "v:0", "stream=height") == "1920"
    with pytest.raises(RenderError):
        render_preview(source, tmp_path / "bad.png", spec, 99.0)
