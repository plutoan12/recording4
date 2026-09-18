"""워커 태스크.

지금 단계에서는 원본 파일 검사만 구현합니다. 외부 유료 API 호출은 없습니다.
"""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal

from adminapi.db import get_session_factory
from adminapi.models import SourceAsset
from adminapi.storage import get_storage
from worker.celery_app import celery_app
from worker.media import ProbeError, probe

logger = logging.getLogger(__name__)

MIN_DURATION_SECONDS = 1.0


@celery_app.task(name="worker.tasks.verify_source_asset", bind=True, max_retries=3)
def verify_source_asset(self, source_asset_id: str) -> dict[str, str]:  # noqa: ANN001
    """원본의 형식·길이·해상도를 검사합니다.

    재전달로 같은 태스크가 두 번 와도 결과가 같습니다. 이미 verified인 원본은
    다시 검사하지 않습니다.
    """
    session_factory = get_session_factory()
    with session_factory() as session:
        asset = session.get(SourceAsset, uuid.UUID(source_asset_id))
        if asset is None:
            logger.warning("원본을 찾을 수 없습니다: %s", source_asset_id)
            return {"status": "missing"}
        if asset.upload_state == "verified":
            return {"status": "already_verified"}

        storage = get_storage()
        signer = getattr(storage, "internal_get_url", storage.presigned_get_url)
        url = signer(asset.storage_key, 900)
        try:
            info = probe(url)
        except ProbeError as exc:
            # 입력 오류는 사람이 고쳐야 하므로 재시도하지 않습니다.
            asset.upload_state = "rejected"
            asset.probe_error = str(exc)
            session.commit()
            logger.info("원본 검사 실패 asset=%s", asset.id)
            return {"status": "rejected"}

        if info.duration_seconds < MIN_DURATION_SECONDS:
            asset.upload_state = "rejected"
            asset.probe_error = f"영상이 너무 짧습니다: {info.duration_seconds:.3f}초"
            session.commit()
            return {"status": "rejected"}

        asset.duration_seconds = Decimal(f"{info.duration_seconds:.3f}")
        asset.width = info.width
        asset.height = info.height
        asset.upload_state = "verified"
        asset.probe_error = None
        session.commit()
        logger.info("원본 검사 완료 asset=%s", asset.id)
        return {"status": "verified"}
