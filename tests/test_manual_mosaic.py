"""User-selected masks must cover only the selected output time/area and fail closed."""

import json
import shutil
import statistics
import subprocess

import pytest
from pydantic import ValidationError

from pipeline.editing import EditSpec
from worker.rendering import RenderError, render_clip, render_preview

REGION = {"start": 1, "end": 2, "x": 0.25, "y": 0.25, "width": 0.5, "height": 0.5, "block_size": 30}


def test_region_times_belong_to_the_edited_output():
    spec = EditSpec(
        start=10,
        end=100,
        segments=[{"start": 10, "end": 16, "speed": 2}],
        mosaic_regions=[REGION],
    )
    assert spec.model_dump()["mosaic_regions"] == [REGION]
    with pytest.raises(ValidationError, match="모자이크"):
        EditSpec(
            start=10,
            end=100,
            segments=[{"start": 10, "end": 16, "speed": 2}],
            mosaic_regions=[{**REGION, "end": 4}],
        )


@pytest.mark.parametrize(
    "patch",
    [
        {"start": -1},
        {"end": 1},
        {"end": float("inf")},
        {"x": -0.1},
        {"x": 0.8},
        {"y": 0.8},
        {"width": 0},
        {"height": 2},
    ],
)
def test_invalid_region_is_rejected(patch):
    with pytest.raises(ValidationError):
        EditSpec(start=0, end=3, mosaic_regions=[{**REGION, **patch}])


def test_too_many_regions_are_rejected():
    with pytest.raises(ValidationError):
        EditSpec(start=0, end=3, mosaic_regions=[REGION] * 21)


@pytest.fixture
def ffmpeg():
    binary = shutil.which("ffmpeg")
    if not binary:
        pytest.skip("FFmpeg required; CI installs it")
    return binary


def make_checker(binary, path, *, audio=True):
    image = path.with_suffix(".pgm")
    pixels = bytes(32 if (x // 4 + y // 4) % 2 else 224 for y in range(320) for x in range(180))
    image.write_bytes(b"P5\n180 320\n255\n" + pixels)
    command = [
        binary,
        "-v",
        "error",
        "-nostdin",
        "-y",
        "-loop",
        "1",
        "-framerate",
        "10",
        "-i",
        str(image),
    ]
    if audio:
        command += ["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000"]
    subprocess.run(
        [*command, "-t", "6", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(path)],
        check=True,
        capture_output=True,
    )


def gray_frame(binary, path, at=0):
    return subprocess.run(
        [
            binary,
            "-v",
            "error",
            "-i",
            str(path),
            "-ss",
            str(at),
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "gray",
            "pipe:1",
        ],
        check=True,
        capture_output=True,
    ).stdout


def variance(frame, x1, y1, x2, y2):
    assert len(frame) == 180 * 320
    return statistics.pvariance(frame[y * 180 + x] for y in range(y1, y2) for x in range(x1, x2))


@pytest.mark.parametrize("kind", ["single_cut", "joined_speed", "no_audio"])
def test_real_masks_use_output_time_preserve_other_areas_and_audio(ffmpeg, tmp_path, kind):
    source, baseline, masked = (tmp_path / name for name in ("in.mp4", "base.mp4", "out.mp4"))
    make_checker(ffmpeg, source, audio=kind != "no_audio")
    values = {"start": 2, "end": 5, "width": 180, "height": 320, "burn_subtitles": False}
    if kind == "joined_speed":
        values.update(
            start=0, end=6, segments=[{"start": 0, "end": 1}, {"start": 2, "end": 6, "speed": 2}]
        )
    render_clip(source, baseline, EditSpec(**values), has_audio=kind != "no_audio")
    render_clip(
        source, masked, EditSpec(**values, mosaic_regions=[REGION]), has_audio=kind != "no_audio"
    )
    for at, hidden in [(0.5, False), (1, True), (1.9, True), (2, False), (2.5, False)]:
        frame = gray_frame(ffmpeg, masked, at)
        inside = variance(frame, 60, 100, 120, 220)
        assert inside < 200 if hidden else inside > 5000
        assert variance(frame, 4, 4, 32, 60) > 5000
    if kind != "no_audio":

        def pcm(path):
            return subprocess.run(
                [ffmpeg, "-v", "error", "-i", str(path), "-vn", "-f", "s16le", "pipe:1"],
                capture_output=True,
                check=True,
            ).stdout

        assert pcm(masked) == pcm(baseline)
    else:
        streams = json.loads(
            subprocess.run(
                [
                    shutil.which("ffprobe"),
                    "-v",
                    "error",
                    "-show_streams",
                    "-of",
                    "json",
                    str(masked),
                ],
                capture_output=True,
                check=True,
            ).stdout
        )["streams"]
        assert [s["codec_type"] for s in streams] == ["video"]


def test_real_preview_shows_regions_at_the_requested_output_time(ffmpeg, tmp_path):
    source, output = tmp_path / "in.mp4", tmp_path / "preview.png"
    make_checker(ffmpeg, source)
    spec = EditSpec(start=2, end=5, width=180, height=320, mosaic_regions=[REGION])
    render_preview(source, output, spec, 1.5)
    assert variance(gray_frame(ffmpeg, output), 60, 100, 120, 220) < 200
    render_preview(source, output, spec, 2.5)
    assert variance(gray_frame(ffmpeg, output), 60, 100, 120, 220) > 5000


def test_workflow_composition_keeps_manual_masks(ffmpeg, tmp_path):
    from worker.composition import render_final

    source, output = tmp_path / "in.mp4", tmp_path / "out.mp4"
    make_checker(ffmpeg, source)
    render_final(
        source,
        output,
        cues=[],
        start=2,
        duration=3,
        clip=EditSpec(start=2, end=5, width=180, height=320, mosaic_regions=[REGION]),
    )
    assert variance(gray_frame(ffmpeg, output, 1.5), 60, 100, 120, 220) < 200
    assert variance(gray_frame(ffmpeg, output, 2.5), 60, 100, 120, 220) > 5000


def test_multiple_regions_preserve_the_middle_of_the_canvas(ffmpeg, tmp_path):
    source, output = tmp_path / "in.mp4", tmp_path / "out.mp4"
    make_checker(ffmpeg, source)
    spec = EditSpec(
        start=0,
        end=3,
        width=180,
        height=320,
        mosaic_regions=[
            {**REGION, "x": 0, "y": 0, "width": 0.25, "height": 0.25},
            {**REGION, "start": 0, "end": 3, "x": 0.75, "y": 0.75, "width": 0.25, "height": 0.25},
        ],
    )
    render_clip(source, output, spec)
    for at, first_hidden in [(0.5, False), (1.5, True), (2.5, False)]:
        frame = gray_frame(ffmpeg, output, at)
        assert (
            variance(frame, 4, 4, 40, 72) < 200
            if first_hidden
            else variance(frame, 4, 4, 40, 72) > 5000
        )
        assert variance(frame, 140, 246, 179, 319) < 200
        assert variance(frame, 60, 100, 120, 220) > 5000


@pytest.mark.parametrize("empty_success", [False, True])
def test_mask_failure_does_not_publish_unmasked_output(
    ffmpeg, tmp_path, monkeypatch, empty_success
):
    source, output = tmp_path / "in.mp4", tmp_path / "out.mp4"
    make_checker(ffmpeg, source)
    output.write_bytes(b"previous-reviewed-version")
    real_run = subprocess.run

    def fail_mask(command, *args, **kwargs):
        if (
            "-filter_complex" in command
            and "overlay=" in command[command.index("-filter_complex") + 1]
        ):
            if empty_success:
                from pathlib import Path

                Path(command[-1]).touch()
            return subprocess.CompletedProcess(command, 0 if empty_success else 1, b"", b"failure")
        return real_run(command, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", fail_mask)
    with pytest.raises(RenderError):
        render_clip(
            source, output, EditSpec(start=0, end=3, width=180, height=320, mosaic_regions=[REGION])
        )
    assert output.read_bytes() == b"previous-reviewed-version"
