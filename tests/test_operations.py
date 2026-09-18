from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from adminapi.config import Settings
from adminapi.storage import S3Storage
from worker import backup, media


def test_internal_probe_url_does_not_use_browser_host():
    storage = S3Storage(
        Settings(
            s3_endpoint_url="http://minio:9000", s3_public_endpoint_url="http://localhost:18444"
        )
    )
    assert storage.internal_get_url("source.mp4", 60).startswith("http://minio:9000/")
    assert storage.presigned_get_url("source.mp4", 60).startswith("http://localhost:18444/")


def test_probe_failure_does_not_expose_signed_url(monkeypatch):
    monkeypatch.setattr(media, "ffprobe_available", lambda: True)
    monkeypatch.setattr(
        media.subprocess,
        "run",
        lambda *a, **kw: SimpleNamespace(
            returncode=1, stderr="https://host?X-Amz-Signature=secret"
        ),
    )
    with pytest.raises(media.ProbeError) as caught:
        media.probe("https://host?X-Amz-Signature=secret")
    assert "secret" not in str(caught.value)


def test_media_backup_is_incremental_and_keys_cannot_escape_directory(tmp_path, monkeypatch):
    page = {"Contents": [{"Key": "../../escape", "ETag": "etag", "Size": 5}]}
    client = Mock()
    client.get_paginator.return_value.paginate.return_value = [page]
    downloads = []

    def download(key, target):
        downloads.append(key)
        target.write_bytes(b"media")

    monkeypatch.setattr(
        backup,
        "get_storage",
        lambda: SimpleNamespace(_client=client, _bucket="test", download_file=download),
    )
    root = tmp_path / "backups"
    assert backup.snapshot(root)["count"] == 1
    assert backup.snapshot(root)["count"] == 1
    assert downloads == ["../../escape"]
    files = list((root / "objects").iterdir())
    assert len(files) == 1 and files[0].read_bytes() == b"media"
    assert not (tmp_path / "escape").exists()


def test_ops_init_keeps_credentials_private_and_does_not_rotate(tmp_path):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "r4ops", Path(__file__).parents[1] / "scripts/ops.py"
    )
    ops = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ops)
    ops.RUNTIME = tmp_path / "runtime"
    ops.ENV_FILE = ops.RUNTIME / "production.env"
    ops.initialize()
    initial = ops.ENV_FILE.read_text()
    ops.initialize()
    assert ops.ENV_FILE.read_text() == initial
    assert ops.ENV_FILE.stat().st_mode & 0o777 == 0o600
    assert "R4_PAID_PROCESSING_ENABLED=false" in initial
    assert "R4_YOUTUBE_UPLOAD_ENABLED=false" in initial


def test_expired_work_is_requeued_once_and_live_lease_is_preserved(session, user):
    from datetime import timedelta

    from adminapi.models import Job, OutboxMessage, SourceAsset, utcnow
    from pipeline.states import JobState
    from worker.operations import recover_expired

    asset = SourceAsset(
        storage_key="recovery-source", original_filename="test.mp4", created_by_id=user.id
    )
    session.add(asset)
    session.flush()
    expired = Job(
        source_asset_id=asset.id,
        target_language="en",
        created_by_id=user.id,
        state=JobState.PROCESSING,
        lease_token="expired",
        lease_until=utcnow() - timedelta(seconds=1),
    )
    live = Job(
        source_asset_id=asset.id,
        target_language="en",
        created_by_id=user.id,
        state=JobState.PROCESSING,
        lease_token="live",
        lease_until=utcnow() + timedelta(hours=1),
    )
    session.add_all([expired, live])
    session.commit()
    recover_expired(session)
    session.commit()
    recover_expired(session)
    session.commit()
    messages = session.query(OutboxMessage).all()
    assert len(messages) == 1
    assert messages[0].payload == {"job_id": str(expired.id)}
    assert live.lease_token == "live"
