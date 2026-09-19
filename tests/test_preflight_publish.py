"""게시 직전 점검. 업로드가 실패할 이유를 올리기 전에 찾습니다."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def preflight():
    spec = importlib.util.spec_from_file_location(
        "r4preflight", Path(__file__).parents[1] / "scripts/preflight_publish.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write(path: Path, data: dict, mode: int = 0o600) -> Path:
    path.write_text(json.dumps(data), encoding="utf-8")
    path.chmod(mode)
    return path


GOOD = {
    "refresh_token": "짧은값",
    "scopes": ["https://www.googleapis.com/auth/youtube.upload"],
}


def test_a_complete_credentials_file_has_no_problems(preflight, tmp_path) -> None:
    assert preflight.check_credentials_file(write(tmp_path / "t.json", GOOD)) == []


def test_missing_refresh_token_is_reported(preflight, tmp_path) -> None:
    """갱신 토큰이 없으면 처음 한 번만 되고 다음부터 막힙니다."""
    data = {**GOOD}
    del data["refresh_token"]
    problems = preflight.check_credentials_file(write(tmp_path / "t.json", data))
    assert any("갱신 토큰" in p for p in problems)


def test_missing_upload_scope_is_reported(preflight, tmp_path) -> None:
    data = {**GOOD, "scopes": ["https://www.googleapis.com/auth/youtube.readonly"]}
    problems = preflight.check_credentials_file(write(tmp_path / "t.json", data))
    assert any("업로드 권한" in p for p in problems)


def test_world_readable_credentials_are_reported(preflight, tmp_path) -> None:
    problems = preflight.check_credentials_file(write(tmp_path / "t.json", GOOD, mode=0o644))
    assert any("읽을 수 있습니다" in p for p in problems)


def test_a_different_channel_stops_the_upload(preflight) -> None:
    """이대로 올리면 승인한 것과 다른 채널에 올라갑니다. 되돌릴 수 없습니다."""
    problems = preflight.check_channel([{"id": "UC-real"}], "UC-configured")
    assert len(problems) == 1
    assert "UC-real" in problems[0]


def test_the_configured_channel_passes(preflight) -> None:
    assert preflight.check_channel([{"id": "UC-a"}, {"id": "UC-b"}], "UC-b") == []


def test_upload_switch_must_be_on(preflight) -> None:
    assert preflight.check_enabled("true") == []
    assert preflight.check_enabled("false")
    assert preflight.check_enabled(None)


def test_a_file_without_scopes_is_reported_not_passed(preflight, tmp_path) -> None:
    """모르는 것은 모른다고 적습니다. 조용히 통과시키면 점검을 둔 뜻이 없습니다."""
    data = {**GOOD}
    del data["scopes"]
    problems = preflight.check_credentials_file(write(tmp_path / "t.json", data))
    assert any("확인하지 못했습니다" in p for p in problems)


def test_caption_scope_is_only_required_when_captions_are_enabled(preflight, tmp_path) -> None:
    """자막 트랙을 올리려면 force-ssl이 필요합니다. 끈 상태에서는 요구하지 않습니다."""
    path = write(tmp_path / "t.json", GOOD)
    assert preflight.check_credentials_file(path) == []
    problems = preflight.check_credentials_file(path, captions=True)
    assert any("force-ssl" in problem for problem in problems)

    with_scope = dict(GOOD)
    with_scope["scopes"] = [*GOOD["scopes"], "https://www.googleapis.com/auth/youtube.force-ssl"]
    granted = write(tmp_path / "with-scope.json", with_scope)
    assert preflight.check_credentials_file(granted, captions=True) == []
