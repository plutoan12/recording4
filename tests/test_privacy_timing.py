"""Real media I/O around a stand-in for EgoBlur's slow model inference."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from worker import privacy


def ffmpeg(*args: str) -> bytes:
    return subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", *args],
        check=True,
        capture_output=True,
        timeout=30,
    ).stdout


def streams(path: Path) -> list[dict]:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(path)],
        check=True,
        capture_output=True,
        timeout=30,
    )
    return json.loads(result.stdout)["streams"]


@pytest.fixture
def egoblur(monkeypatch, tmp_path):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg required; CI installs it")
    model = tmp_path / "model.jit"
    model.touch()
    monkeypatch.setenv("R4_EGOBLUR_BINARY", "/fake/egoblur")
    monkeypatch.setenv("R4_EGOBLUR_FACE_MODEL", str(model))
    real_run = privacy._run
    behavior = {"fps_override": None, "drop_frame": False}

    def fake_model(command, output, timeout, message):
        if command[0] != "/fake/egoblur":
            return real_run(command, output, timeout, message)
        # Gen1 writes all decoded frames at an integer FPS (default30), without audio.
        source = Path(command[command.index("--input_video_path") + 1])
        count = int(streams(source)[0]["nb_frames"]) - int(behavior["drop_frame"])
        fps = behavior["fps_override"] or (
            command[command.index("--output_video_fps") + 1]
            if "--output_video_fps" in command
            else "30"
        )
        ffmpeg(
            "-f", "lavfi", "-i", f"color=black:s=320x180:r={fps}",
            "-frames:v", str(count), "-c:v", "libx264", "-threads", "1", str(output),
        )  # fmt: skip

    monkeypatch.setattr(privacy, "_run", fake_model)
    return behavior


def source_video(path: Path, rate: str, audio: bool = True) -> None:
    args = ["-f", "lavfi", "-i", f"testsrc2=size=320x180:rate={rate}"]
    if audio:
        args += ["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000"]
    ffmpeg(*args, "-t", "2", "-c:v", "libx264", "-threads", "1", "-c:a", "aac", str(path))


@pytest.mark.parametrize("rate", ["24", "30"])
@pytest.mark.parametrize("audio", [False, True])
def test_egoblur_keeps_timing_and_audio_but_only_redacted_pixels(egoblur, tmp_path, rate, audio):
    source, output = tmp_path / "in.mp4", tmp_path / "out.mp4"
    source_video(source, rate, audio)
    privacy.redact_faces(source, output, 20, "egoblur")
    result = streams(output)
    video = next(s for s in result if s["codec_type"] == "video")
    assert video["avg_frame_rate"] == f"{rate}/1"
    assert float(video["duration"]) == pytest.approx(2.0, abs=0.001)
    assert any(s["codec_type"] == "audio" for s in result) is audio
    pixels = ffmpeg("-i", str(output), "-an", "-pix_fmt", "rgb24", "-f", "rawvideo", "-")
    assert pixels and max(pixels) == 0  # Must use the model's black/redacted frames.
    if audio:
        decode = ("-vn", "-f", "s16le", "-acodec", "pcm_s16le", "-")
        assert ffmpeg("-i", str(output), *decode) == ffmpeg("-i", str(source), *decode)


def test_egoblur_refuses_fractional_fps_instead_of_rounding(egoblur, tmp_path):
    source, output = tmp_path / "in.mp4", tmp_path / "out.mp4"
    source_video(source, "24000/1001")
    with pytest.raises(privacy.PrivacyError):
        privacy.redact_faces(source, output, 20, "egoblur")
    assert not output.exists()


@pytest.mark.parametrize("fault", ["fps_override", "drop_frame"])
def test_egoblur_refuses_changed_output_timing(egoblur, tmp_path, fault):
    source, output = tmp_path / "in.mp4", tmp_path / "out.mp4"
    source_video(source, "24")
    egoblur[fault] = "30" if fault == "fps_override" else True
    with pytest.raises(privacy.PrivacyError):
        privacy.redact_faces(source, output, 20, "egoblur")
    assert not output.exists()


def test_egoblur_refuses_unreadable_video(egoblur, tmp_path):
    source, output = tmp_path / "in.mp4", tmp_path / "out.mp4"
    source.write_bytes(b"not video")
    with pytest.raises(privacy.PrivacyError):
        privacy.redact_faces(source, output, 20, "egoblur")
    assert not output.exists()
