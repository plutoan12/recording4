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


@pytest.mark.parametrize("burn", [True, False])
def test_frozen_download_strips_emphasis_without_losing_timing(tmp_path, burn):
    spec = joined(
        burn_subtitles=burn, cues=[{"start": 5, "end": 7, "text": "This is [[important]]"}]
    )
    files = write_subtitles(tmp_path / "captions.ass", spec)
    for fmt in ("srt", "vtt"):
        cue = pysubs2.SSAFile.from_string(files[fmt])[0]
        assert cue.plaintext == "This is important"
        assert (cue.start, cue.end) == (2200, 3200)


def test_automatic_reframe_matches_explicit_source_timed_track(tmp_path, monkeypatch):
    from test_render_integration import ffmpeg_or_skip, make_source
    from worker import analysis
    from worker.rendering import render_clip

    source = tmp_path / "source.mp4"
    make_source(ffmpeg_or_skip(), source, 6)
    spec = EditSpec(
        start=4,
        end=6,
        width=180,
        height=320,
        mode="crop",
        reframe={"deadzone": 0, "max_speed": 2},
        burn_subtitles=False,
    )
    automatic, expected = tmp_path / "automatic.mp4", tmp_path / "expected.mp4"
    # The detection boundary emits times relative to the requested window.
    monkeypatch.setattr(analysis, "face_track", lambda source, **kw: ([(0, 0.2), (1, 0.8)], "stub"))
    render_clip(source, automatic, spec, has_audio=True)
    render_clip(source, expected, spec, faces=[(4, 0.2), (5, 0.8)], has_audio=True)
    assert automatic.read_bytes() == expected.read_bytes()


@pytest.mark.parametrize("start", [0, 1])
def test_animated_preview_shows_elapsed_caption_on_nonzero_frame(tmp_path, start):
    import subprocess

    from test_render_integration import ffmpeg_or_skip
    from worker.rendering import render_preview

    source = tmp_path / "black.mp4"
    subprocess.run(
        [
            ffmpeg_or_skip(),
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=black:s=180x320:r=30:d=5",
            "-c:v",
            "libx264",
            str(source),
        ],
        check=True,
    )
    spec = EditSpec(
        start=start,
        end=start + 3,
        width=180,
        height=320,
        subtitle_animation="fade",
        cues=[{"start": start, "end": start + 3, "text": "hello"}],
    )
    animated, blank = tmp_path / "animated.png", tmp_path / "blank.png"
    render_preview(source, animated, spec, 1.5)
    render_preview(source, blank, spec.model_copy(update={"cues": []}), 1.5)
    assert animated.read_bytes() != blank.read_bytes()
