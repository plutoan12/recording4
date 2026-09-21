from pathlib import Path

import pytest

from worker import rendering


def test_mosaic_binary_is_required_only_when_requested(monkeypatch):
    monkeypatch.delenv("R4_DEFACE_BINARY", raising=False)
    monkeypatch.setattr(rendering.shutil, "which", lambda name: None)
    with pytest.raises(rendering.RenderError, match="모자이크"):
        rendering.deface_binary()


def test_mosaic_command_preserves_audio_and_tile_size(monkeypatch, tmp_path):
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        Path(command[-1]).write_bytes(b"video")
        return type("Completed", (), {"returncode": 0})()

    monkeypatch.setattr(rendering, "deface_binary", lambda: "/usr/local/bin/deface")
    monkeypatch.setattr(rendering.subprocess, "run", fake_run)
    rendering._mosaic_faces(tmp_path / "in.mp4", tmp_path / "out.mp4", 24)
    assert calls[0][0] == [
        "/usr/local/bin/deface",
        str(tmp_path / "in.mp4"),
        "--replacewith",
        "mosaic",
        "--mosaicsize",
        "24",
        "--keep-audio",
        "--output",
        str(tmp_path / "out.mp4"),
    ]
