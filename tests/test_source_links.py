import subprocess
from pathlib import Path

import pytest
from sqlalchemy import select

from adminapi.models import OutboxMessage, SourceAsset
from pipeline.source_links import youtube_url
from worker import link_import


@pytest.mark.parametrize(
    "url",
    [
        "https://youtu.be/abcdefghijk?si=tracking",
        "https://www.youtube.com/watch?v=abcdefghijk&list=other",
        "https://m.youtube.com/shorts/abcdefghijk",
    ],
)
def test_canonical_single_video(url):
    assert youtube_url(url) == "https://www.youtube.com/watch?v=abcdefghijk"


@pytest.mark.parametrize(
    "url",
    [
        "http://youtube.com/watch?v=abcdefghijk",
        "https://127.0.0.1/video.mp4",
        "file:///etc/passwd",
        "https://youtube.com.evil.test/watch?v=abcdefghijk",
        "https://user:pass@youtube.com/watch?v=abcdefghijk",
        "https://youtube.com:8443/watch?v=abcdefghijk",
        "https://youtube.com/playlist?list=abc",
        "https://youtu.be/../abcdefghijk",
    ],
)
def test_invalid_source_rejected(url):
    with pytest.raises(ValueError):
        youtube_url(url)


def test_import_requires_auth(client):
    assert client.post("/source-assets/import-link", json={"url": "x"}).status_code == 401


def test_import_download_verify_and_redelivery(client, auth_headers, session, monkeypatch):
    result = client.post(
        "/source-assets/import-link",
        headers=auth_headers,
        json={"url": "https://youtu.be/abcdefghijk?si=tracking"},
    )
    assert result.status_code == 202
    message = session.scalar(select(OutboxMessage))
    assert message.payload["url"] == "https://www.youtube.com/watch?v=abcdefghijk"
    calls = []

    def download(args, **kwargs):
        assert "R4_ADMIN_PASSWORD" not in kwargs["env"]
        Path(args[-2]).write_bytes(b"video")
        calls.append(args)

    class Storage:
        def upload_file(self, key, source, content_type):
            assert source.read_bytes() == b"video"

    monkeypatch.setattr(link_import, "run_downloader", download)
    monkeypatch.setattr(link_import, "get_storage", Storage)
    assert link_import.import_source_link(**message.payload)["status"] == "uploaded"
    assert link_import.import_source_link(**message.payload)["status"] == "not_pending"
    assert len(calls) == 1
    session.expire_all()
    assert session.scalar(select(SourceAsset)).byte_size == 5
    assert len(list(session.scalars(select(OutboxMessage)))) == 2


def test_download_failure_is_safe_and_visible(client, auth_headers, session, monkeypatch):
    client.post(
        "/source-assets/import-link",
        headers=auth_headers,
        json={"url": "https://youtu.be/abcdefghijk"},
    )
    message = session.scalar(select(OutboxMessage))

    def fail(*args, **kwargs):
        raise subprocess.TimeoutExpired("secret-url-token", 600)

    monkeypatch.setattr(link_import, "run_downloader", fail)
    assert link_import.import_source_link(**message.payload)["status"] == "rejected"
    session.expire_all()
    asset = session.scalar(select(SourceAsset))
    assert "secret" not in asset.probe_error
    assert "가져오기 실패" in asset.probe_error


def test_timeout_terminates_downloader_process_group(monkeypatch):
    killed = []

    class Process:
        pid = 12345

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def communicate(self, timeout):
            raise subprocess.TimeoutExpired("downloader", timeout)

        def wait(self):
            return -9

    def popen(args, **kwargs):
        assert kwargs["start_new_session"] is True
        return Process()

    monkeypatch.setattr(link_import.subprocess, "Popen", popen)
    monkeypatch.setattr(link_import.os, "killpg", lambda pid, sig: killed.append(pid))
    with pytest.raises(subprocess.TimeoutExpired):
        link_import.run_downloader(["downloader"], timeout=600, check=True)
    assert killed == [12345]
