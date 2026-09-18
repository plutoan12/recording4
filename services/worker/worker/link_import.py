"""Bounded public YouTube import. No cookies, credentials or generic URL extractor."""

from __future__ import annotations

import hashlib
import os
import signal
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

from sqlalchemy import select

from adminapi.config import get_settings
from adminapi.db import get_session_factory
from adminapi.models import SourceAsset
from adminapi.outbox import enqueue
from adminapi.storage import get_storage
from pipeline.source_links import youtube_url
from worker.celery_app import celery_app


def run_downloader(args, **kwargs):
    timeout = kwargs.pop("timeout")
    kwargs.pop("check")
    with subprocess.Popen(args, start_new_session=True, **kwargs) as process:
        try:
            process.communicate(timeout=timeout)
            if process.returncode:
                raise subprocess.CalledProcessError(process.returncode, args)
        except BaseException:
            # FFmpeg/Node children must stop too when the download times out.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
            raise


@celery_app.task(name="worker.link_import.import_source_link", soft_time_limit=660, time_limit=690)
def import_source_link(source_asset_id: str, url: str):
    factory = get_session_factory()
    # Keep the row lock until commit. Redelivery after worker death restarts safely;
    # concurrent duplicate deliveries cannot race a source verification.
    with factory() as session:
        asset = session.scalar(
            select(SourceAsset)
            .where(SourceAsset.id == uuid.UUID(source_asset_id))
            .with_for_update()
        )
        if asset is None or asset.upload_state != "awaiting_upload" or asset.byte_size is not None:
            return {"status": "not_pending"}
        try:
            url = youtube_url(url)
            limit = min(get_settings().max_source_bytes, 500 * 1024 * 1024)
            with tempfile.TemporaryDirectory(prefix="r4-link-") as temp:
                target = Path(temp) / "source.mp4"
                run_downloader(
                    [sys.executable, "-m", "worker.link_download", url, str(target), str(limit)],
                    env={
                        k: v
                        for k, v in os.environ.items()
                        if k in {"PATH", "HOME", "PYTHONPATH", "SSL_CERT_FILE"}
                    },
                    check=True,
                    timeout=600,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                size = target.stat().st_size
                if not 0 < size <= limit:
                    raise ValueError("size")
                get_storage().upload_file(asset.storage_key, target, "video/mp4")
                asset.byte_size = size
                with target.open("rb") as stream:
                    asset.checksum = hashlib.file_digest(stream, "sha256").hexdigest()
            asset.upload_state = "uploaded"
            asset.probe_error = None
            enqueue(
                session,
                topic="source_asset.verify",
                payload={"source_asset_id": source_asset_id},
                dedupe_key=f"source_asset.verify:{source_asset_id}",
            )
        except Exception:
            asset.upload_state = "rejected"
            asset.probe_error = (
                "링크 가져오기 실패: 다운로드 제한·지원 형식·네트워크 또는 "
                "500MB/10분 처리 한도를 확인하세요. 원본 파일을 직접 등록할 수도 있습니다."
            )
        session.commit()
        return {"status": asset.upload_state}
