"""검증용 음성을 묶는 도구. 여기가 틀리면 검증 결과를 믿을 수 없습니다."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def sample():
    spec = importlib.util.spec_from_file_location(
        "r4speech_sample", Path(__file__).parents[1] / "scripts/speech_sample.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_listing_uses_absolute_paths(sample, tmp_path) -> None:
    """이름만 적으면 다른 폴더의 조각을 못 찾습니다. ffmpeg는 그걸 빼고도
    성공으로 끝내서, 정답과 어긋난 짧은 음성이 조용히 만들어집니다."""
    other = tmp_path / "elsewhere"
    other.mkdir()
    pieces = [tmp_path / "silence.wav", other / "human0.wav"]
    listing = sample.concat_listing(pieces)
    assert f"file '{(other / 'human0.wav').resolve()}'" in listing
    assert listing.count("file '") == 2
    for line in listing.splitlines():
        assert line.startswith("file '/"), line
