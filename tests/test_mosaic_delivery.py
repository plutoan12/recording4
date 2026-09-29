from pathlib import Path

import pytest

from pipeline.editing import EditSpec
from worker import rendering
from worker.privacy import PrivacyError


def test_mosaic_keeps_multicut_and_music_settings(monkeypatch, tmp_path):
    source = tmp_path / "in.mp4"
    source.write_bytes(b"source")
    music = tmp_path / "music.wav"
    music.write_bytes(b"music")
    output = tmp_path / "out.mp4"
    spec = EditSpec(
        start=0,
        end=4,
        mosaic_faces=True,
        mosaic_size=24,
        deface_sensitive=True,
        segments=[{"start": 0, "end": 1}, {"start": 2, "end": 4, "speed": 2}],
        fade_in=0.2,
        music_gain_db=-20,
    )
    captured = {}

    def encode(command, temp, target):
        captured["command"] = command
        target.write_bytes(b"edited-with-music")
        assert target != output

    def redact(source, target, size, backend, sensitive):
        assert source.read_bytes() == b"edited-with-music"
        assert (size, backend) == (24, "deface")
        assert sensitive is True
        target.write_bytes(b"redacted")

    monkeypatch.setattr(rendering, "run_ffmpeg", encode)
    monkeypatch.setattr(rendering, "redact_faces", redact)
    rendering.render_clip(source, output, spec, music=music, has_audio=True)
    assert output.read_bytes() == b"redacted"
    command = captured["command"]
    assert str(music) in command and "-filter_complex" in command
    assert spec.output_seconds == 2


def test_failed_privacy_does_not_publish_unredacted_file(monkeypatch, tmp_path):
    source = tmp_path / "in.mp4"
    source.write_bytes(b"source")
    output = tmp_path / "out.mp4"
    monkeypatch.setattr(
        rendering, "run_ffmpeg", lambda command, temp, target: target.write_bytes(b"raw")
    )

    def failed(*args):
        raise PrivacyError("모자이크 실패")

    monkeypatch.setattr(rendering, "redact_faces", failed)
    with pytest.raises(rendering.RenderError, match="모자이크 실패"):
        rendering.render_clip(source, output, EditSpec(start=0, end=1, mosaic_faces=True))
    assert not output.exists()


def test_empty_redaction_is_rejected(monkeypatch, tmp_path):
    from worker import privacy

    output = tmp_path / "empty.mp4"
    output.touch()
    monkeypatch.setattr(
        privacy.subprocess, "run", lambda *a, **k: type("Done", (), {"returncode": 0})()
    )
    with pytest.raises(PrivacyError):
        privacy._run(["unused"], output, 1, "모자이크 실패")


@pytest.mark.parametrize("fail", [False, True])
def test_workflow_preserves_privacy_options_and_never_copies_failed_output(
    monkeypatch, tmp_path, fail
):
    from worker import composition

    source, output = tmp_path / "source.mp4", tmp_path / "final.mp4"
    source.write_bytes(b"source")
    spec = EditSpec(start=0, end=1, mosaic_faces=True, deface_sensitive=True)
    monkeypatch.setattr(
        composition, "ffmpeg", lambda args, **kwargs: Path(args[-1]).write_bytes(b"unredacted")
    )

    def redact(rendered, redacted, size, backend, sensitive):
        assert rendered.read_bytes() == b"unredacted"
        assert sensitive is True and backend == "deface"
        if fail:
            raise rendering.RenderError("모자이크 실패")
        redacted.write_bytes(b"redacted")

    monkeypatch.setattr(composition, "_mosaic_faces", redact)
    if fail:
        with pytest.raises(rendering.RenderError, match="모자이크 실패"):
            composition.render_final(source, output, cues=[], duration=1, clip=spec)
        assert not output.exists()
    else:
        composition.render_final(source, output, cues=[], duration=1, clip=spec)
        assert output.read_bytes() == b"redacted"
