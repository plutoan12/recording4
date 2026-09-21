from pathlib import Path

import pytest

from worker import privacy


def test_deface_command_is_fail_closed(monkeypatch, tmp_path: Path):
    output = tmp_path / "out.mp4"
    seen = {}

    def fake_run(command, output_path, timeout, message):
        seen["command"] = command
        output_path.write_bytes(b"video")

    monkeypatch.setattr(privacy, "_run", fake_run)
    monkeypatch.setenv("R4_DEFACE_BINARY", "/srv/bin/deface")
    privacy.redact_faces(tmp_path / "in.mp4", output, 24)
    assert seen["command"] == [
        "/srv/bin/deface",
        str(tmp_path / "in.mp4"),
        "--replacewith",
        "mosaic",
        "--mosaicsize",
        "24",
        "--keep-audio",
        "--output",
        str(output),
    ]


def test_openscrub_requires_model(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("R4_OPENSCRUB_BINARY", "/srv/bin/openscrub")
    monkeypatch.delenv("R4_OPENSCRUB_FACE_MODEL", raising=False)
    with pytest.raises(privacy.PrivacyError, match="OpenScrub 얼굴 모델"):
        privacy.redact_faces(tmp_path / "in.mp4", tmp_path / "out.mp4", 20, "openscrub")


def test_egoblur_requires_model(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("R4_EGOBLUR_BINARY", "/srv/bin/egoblur-gen1")
    monkeypatch.delenv("R4_EGOBLUR_FACE_MODEL", raising=False)
    with pytest.raises(privacy.PrivacyError, match="EgoBlur 얼굴 모델"):
        privacy.redact_faces(tmp_path / "in.mp4", tmp_path / "out.mp4", 20, "egoblur")
