"""글꼴 내려받기 스크립트. 네트워크 없이 체크섬·재사용·이름 확인 규칙을 봅니다."""

import hashlib
import importlib.util
from pathlib import Path

import pytest

from pipeline.subtitle_fonts import FONT_SOURCES, FontSource


@pytest.fixture
def fetch_fonts():
    spec = importlib.util.spec_from_file_location(
        "r4fetchfonts", Path(__file__).parents[1] / "scripts/fetch_fonts.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def source_for(data: bytes, family: str = "Test Font") -> FontSource:
    return FontSource(
        family=family,
        filename="Test.ttf",
        url="https://example.invalid/Test.ttf",
        sha256=hashlib.sha256(data).hexdigest(),
    )


def test_download_is_verified_and_reused(fetch_fonts, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(fetch_fonts, "download", lambda url, timeout: calls.append(url) or b"font")
    monkeypatch.setattr(fetch_fonts, "families_in", lambda path: ["Test Font", "테스트"])
    source = source_for(b"font")
    assert "받음" in fetch_fonts.fetch(source, tmp_path, timeout=1)
    assert (tmp_path / "Test.ttf").read_bytes() == b"font"
    # 같은 체크섬이 이미 있으면 다시 받지 않습니다.
    assert "이미 있음" in fetch_fonts.fetch(source, tmp_path, timeout=1)
    assert calls == ["https://example.invalid/Test.ttf"]


def test_checksum_mismatch_is_not_installed(fetch_fonts, tmp_path, monkeypatch):
    monkeypatch.setattr(fetch_fonts, "download", lambda url, timeout: b"tampered")
    with pytest.raises(RuntimeError, match="체크섬"):
        fetch_fonts.fetch(source_for(b"font"), tmp_path, timeout=1)
    assert not (tmp_path / "Test.ttf").exists()


def test_family_name_mismatch_fails(fetch_fonts, tmp_path, monkeypatch):
    """이름이 다르면 libass가 조용히 대체하므로 설치 단계에서 실패로 봅니다."""
    monkeypatch.setattr(fetch_fonts, "download", lambda url, timeout: b"font")
    monkeypatch.setattr(fetch_fonts, "families_in", lambda path: ["Other"])
    with pytest.raises(RuntimeError, match="family"):
        fetch_fonts.fetch(source_for(b"font"), tmp_path, timeout=1)
    # fc-scan이 없으면(None) 이름 확인은 건너뜁니다.
    monkeypatch.setattr(fetch_fonts, "families_in", lambda path: None)
    assert "받음" in fetch_fonts.fetch(source_for(b"font"), tmp_path, timeout=1)


def test_main_reports_unknown_family_and_partial_failure(
    fetch_fonts, tmp_path, monkeypatch, capsys
):
    assert fetch_fonts.main(["--out", str(tmp_path), "--only", "Nope"]) == 2
    assert "모르는 글꼴" in capsys.readouterr().err

    def download(url, timeout):
        if "jua" in url:
            raise OSError("offline")
        assert any(s.url == url for s in FONT_SOURCES)
        return b"x"  # 체크섬이 안 맞아 실패합니다.

    monkeypatch.setattr(fetch_fonts, "download", download)
    code = fetch_fonts.main(["--out", str(tmp_path), "--only", "Jua", "Gugi"])
    captured = capsys.readouterr()
    assert code == 1 and "0/2개 준비됨" in captured.out and captured.err.count("실패") == 2
