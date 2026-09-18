"""Actual FFmpeg render, decoding and audio-level checks; no external media."""

import os
import shutil
import subprocess

import pytest

from pipeline.editing import Cue, EditSpec
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
