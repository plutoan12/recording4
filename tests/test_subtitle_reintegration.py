"""PR36 effects must share main's output timeline and frozen caption contract."""

import pysubs2
import pytest
from pydantic import ValidationError

from pipeline.editing import EditSpec
from worker.rendering import moved_face_time, source_time, write_subtitles


def joined(**updates):
    values = dict(
        start=0,
        end=8,
        width=180,
        height=320,
        segments=[{"start": 0, "end": 2}, {"start": 4, "end": 8, "speed": 2}],
        transition={"seconds": 0.3},
        cues=[{"start": 5, "end": 7, "text": "after cut"}],
    )
    return EditSpec(**(values | updates))


def test_transition_length_is_shared_with_mosaic_validation():
    assert joined().output_seconds == pytest.approx(3.7)
    with pytest.raises(ValidationError, match="모자이크"):
        joined(mosaic_regions=[dict(start=3.6, end=3.9, x=0, y=0, width=1, height=1)])


def test_transition_moves_burned_and_downloaded_captions_together(tmp_path):
    path = tmp_path / "captions.ass"
    files = write_subtitles(path, joined())
    displayed = pysubs2.load(str(path))
    downloaded = pysubs2.SSAFile.from_string(files["srt"])
    assert [(e.start, e.end) for e in displayed] == [(2200, 3200)]
    assert [(e.start, e.end, e.plaintext) for e in downloaded] == [(2200, 3200, "after cut")]


def test_transition_moves_faces_and_preview_to_the_same_source_time():
    spec = joined()
    assert moved_face_time(5, spec) == pytest.approx(2.2)
    assert source_time(spec, 2.2) == pytest.approx(5)


def test_sticker_spans_are_clipped_scaled_and_shifted_with_cuts(tmp_path):
    path = tmp_path / "captions.ass"
    write_subtitles(path, joined(stickers=[{"kind": "star", "start": 5, "end": 7}]))
    events = [e for e in pysubs2.load(str(path)) if e.style == "Sticker"]
    assert [(e.start, e.end) for e in events] == [(2200, 3200)]


def test_layered_template_download_has_one_plain_cue_and_no_drawings(tmp_path):
    files = write_subtitles(tmp_path / "captions.ass", joined(subtitle_template="bubble-white"))
    events = pysubs2.SSAFile.from_string(files["vtt"])
    assert [e.plaintext for e in events] == ["after cut"]


@pytest.mark.parametrize("rate,unit", [("30", 1.0), ("30000/1001", 1.001)])
def test_transition_speed_and_mosaic_preserve_every_output_frame(tmp_path, rate, unit):
    import shutil
    import subprocess
    from fractions import Fraction

    from test_render_timing import source_video, timeline
    from worker.rendering import render_clip

    binary = shutil.which("ffmpeg")
    if not binary or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg and ffprobe required")
    source, output = tmp_path / "source.mp4", tmp_path / "result.mp4"
    source_video(binary, source, rate, 6 * unit)
    spec = EditSpec(
        start=0,
        end=6 * unit,
        width=180,
        height=320,
        segments=[{"start": 0, "end": unit}, {"start": 2 * unit, "end": 6 * unit, "speed": 2}],
        transition={"seconds": 0.3},
        denoise="soft",
        mosaic_regions=[dict(start=2, end=2.6, x=0, y=0, width=1, height=0.5)],
    )
    render_clip(source, output, spec, has_audio=True)
    data = timeline(output)
    stream, frames = data["streams"][0], data["frames"]
    assert Fraction(stream["avg_frame_rate"]) == Fraction(rate)
    assert int(stream["nb_frames"]) == int(stream["nb_read_frames"]) == len(frames) == 81
    assert float(stream["duration"]) == pytest.approx(81 / float(Fraction(rate)), abs=0.000002)
    assert [float(f["best_effort_timestamp_time"]) for f in frames] == pytest.approx(
        [float(Fraction(i) / Fraction(rate)) for i in range(81)], abs=0.000002
    )
    pcm = subprocess.run(
        [
            binary,
            "-v",
            "error",
            "-i",
            str(output),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "48000",
            "-f",
            "s16le",
            "pipe:1",
        ],
        check=True,
        capture_output=True,
    ).stdout
    assert len(pcm) / 96000 == pytest.approx(spec.output_seconds, abs=0.06)
    assert any(pcm)
