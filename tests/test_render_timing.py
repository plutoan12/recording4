"""Decode the complete edited timeline, including the last displayed frame."""

import json
import shutil
import subprocess
from fractions import Fraction

import pytest

from pipeline.editing import EditSpec
from worker.rendering import RenderError, render_clip, source_frame_rate


@pytest.fixture
def ffmpeg():
    binary = shutil.which("ffmpeg")
    if not binary or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg/ffprobe required; CI installs them")
    return binary


def source_video(binary, path, rate, seconds):
    subprocess.run(
        [
            binary, "-v", "error", "-f", "lavfi", "-i",
            f"testsrc2=size=180x320:rate={rate}",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
            "-t", str(seconds), "-c:v", "libx264", "-c:a", "aac", str(path),
        ],
        check=True, capture_output=True,
    )  # fmt: skip


def timeline(path):
    return json.loads(
        subprocess.run(
            [
                shutil.which("ffprobe"), "-v", "error", "-select_streams", "v:0",
                "-count_frames", "-show_streams", "-show_frames", "-of", "json", str(path),
            ],
            check=True, capture_output=True,
        ).stdout
    )  # fmt: skip


@pytest.mark.parametrize(
    "rate,unit,count", [("10", 1, 30), ("30", 1, 90), ("30000/1001", 1.001, 90)]
)
@pytest.mark.parametrize("ending", ["fast", "normal", "slow"])
def test_joined_speed_keeps_source_cadence_and_full_end(
    ffmpeg, tmp_path, rate, unit, count, ending
):
    source, output = tmp_path / "source.mp4", tmp_path / "out.mp4"
    source_video(ffmpeg, source, rate, 6 * unit)
    spans = {
        "fast": [(0, 1, 1), (2, 6, 2)],
        "normal": [(0, 4, 2), (5, 6, 1)],
        "slow": [(0, 1, 1), (2, 3, 0.5)],
    }[ending]
    spec = EditSpec(
        start=0,
        end=6 * unit,
        width=180,
        height=320,
        burn_subtitles=False,
        segments=[{"start": a * unit, "end": b * unit, "speed": speed} for a, b, speed in spans],
    )
    render_clip(source, output, spec, has_audio=True)
    data = timeline(output)
    stream, frames = data["streams"][0], data["frames"]
    # Expected counts describe constant output cadence, not preservation of every
    # source frame after changing playback speed. Values are hand-derived above.
    assert Fraction(stream["avg_frame_rate"]) == Fraction(rate)
    assert int(stream["nb_frames"]) == int(stream["nb_read_frames"]) == len(frames) == count
    assert float(stream["duration"]) == pytest.approx(3 * unit, abs=0.000002)
    expected = [float(Fraction(i) / Fraction(rate)) for i in range(count)]
    assert [float(frame["best_effort_timestamp_time"]) for frame in frames] == pytest.approx(
        expected, abs=0.000002
    )
    # A video-only success must not hide a missing/shortened speech track.
    pcm = subprocess.run(
        [ffmpeg, "-v", "error", "-i", str(output), "-vn", "-ac", "1", "-ar", "48000",
         "-f", "s16le", "pipe:1"],
        check=True, capture_output=True,
    ).stdout  # fmt: skip
    assert len(pcm) / 96000 == pytest.approx(3 * unit, abs=0.06)
    assert any(pcm)


def test_unknown_source_cadence_fails_without_overwriting_output(ffmpeg, tmp_path, monkeypatch):
    source, output = tmp_path / "source.mp4", tmp_path / "existing.mp4"
    source_video(ffmpeg, source, "10", 3)
    output.write_bytes(b"previous reviewed output")
    monkeypatch.setenv("R4_FFPROBE_BINARY", str(tmp_path / "missing-ffprobe"))
    with pytest.raises(RenderError, match="프레임률"):
        render_clip(
            source,
            output,
            EditSpec(start=0, end=3, width=180, height=320, segments=[{"start": 0, "end": 3}]),
            has_audio=True,
        )
    assert output.read_bytes() == b"previous reviewed output"


def test_variable_input_uses_measured_average_cadence(ffmpeg, tmp_path):
    source, output = tmp_path / "variable.mp4", tmp_path / "out.mp4"
    subprocess.run(
        [ffmpeg, "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=180x320:rate=20",
         "-t", "6", "-vf", r"select=if(lt(t\,3)\,not(mod(n\,2))\,1)",
         "-fps_mode", "vfr", "-c:v", "libx264", "-bf", "0", str(source)],
        check=True, capture_output=True,
    )  # fmt: skip
    # 30 frames over the first 3 seconds, then 60 over the last 3: 15fps average.
    assert Fraction(timeline(source)["streams"][0]["avg_frame_rate"]) == 15
    render_clip(
        source,
        output,
        EditSpec(
            start=0,
            end=6,
            width=180,
            height=320,
            burn_subtitles=False,
            segments=[{"start": 0, "end": 1}, {"start": 2, "end": 6, "speed": 2}],
        ),
        has_audio=False,
    )
    data = timeline(output)
    assert Fraction(data["streams"][0]["avg_frame_rate"]) == 15
    assert len(data["frames"]) == int(data["streams"][0]["nb_frames"]) == 45
    assert float(data["streams"][0]["duration"]) == pytest.approx(3, abs=0.000002)


@pytest.mark.parametrize(
    "metadata,expected",
    [
        ({"streams": [{"avg_frame_rate": "0/0", "r_frame_rate": "25/1"}]}, "25/1"),
        ({"streams": [{"avg_frame_rate": "30000/1001", "r_frame_rate": "30/1"}]}, "30000/1001"),
        ({"streams": [{"avg_frame_rate": "0/0", "r_frame_rate": "0/0"}]}, None),
        ({"streams": [{"avg_frame_rate": True}]}, None),
        ({"streams": [{"avg_frame_rate": "1000000/1", "r_frame_rate": "30/1"}]}, None),
        ({"streams": []}, None),
        ({"streams": None}, None),
    ],
)
def test_probe_metadata_does_not_guess_or_expand_an_unsafe_rate(
    monkeypatch, tmp_path, metadata, expected
):
    # The probe is the external boundary. Exercise validation of its response,
    # including metadata that would otherwise make fps duplicate unboundedly.
    monkeypatch.setenv("R4_FFPROBE_BINARY", "configured-probe")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, json.dumps(metadata), ""),
    )
    if expected is None:
        with pytest.raises(RenderError, match="프레임률"):
            source_frame_rate(tmp_path / "private-file.mp4")
    else:
        assert source_frame_rate(tmp_path / "private-file.mp4") == expected
