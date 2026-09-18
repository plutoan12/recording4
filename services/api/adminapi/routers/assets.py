"""원본 등록.

브라우저는 서명 URL로 저장소에 직접 올립니다. API는 URL 발급, 완료 검증,
워커의 파일 검사 요청까지 담당하고 파일 본문은 거치지 않습니다.
"""

from __future__ import annotations

import uuid
from pathlib import PurePosixPath

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from adminapi.config import Settings, get_settings
from adminapi.deps import CurrentUser, SessionDep
from adminapi.models import SourceAsset
from adminapi.outbox import enqueue
from adminapi.schemas import (
    PreviewUrlResponse,
    SourceAssetResponse,
    UploadCompleteRequest,
    UploadRequest,
    UploadResponse,
)
from adminapi.storage import ObjectStorage, build_source_key, get_storage

router = APIRouter(prefix="/source-assets", tags=["source-assets"])

StorageDep = Depends(get_storage)
SettingsDep = Depends(get_settings)


@router.post("", response_model=UploadResponse, status_code=status.HTTP_201_CREATED)
def request_upload(
    payload: UploadRequest,
    user: CurrentUser,
    session: SessionDep,
    storage: ObjectStorage = StorageDep,
    settings: Settings = SettingsDep,
) -> UploadResponse:
    suffix = PurePosixPath(payload.filename.replace("\\", "/")).suffix.lower()
    if suffix not in settings.allowed_source_extensions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"지원하지 않는 확장자입니다: {suffix or '(없음)'}",
        )
    if payload.byte_size > settings.max_source_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="파일이 허용 크기를 넘습니다.",
        )

    key = build_source_key(payload.filename)
    asset = SourceAsset(
        storage_key=key,
        original_filename=PurePosixPath(payload.filename.replace("\\", "/")).name,
        byte_size=payload.byte_size,
        created_by_id=user.id,
        upload_state="awaiting_upload",
    )
    session.add(asset)
    session.flush()
    return UploadResponse(
        source_asset_id=asset.id,
        storage_key=key,
        upload_url=storage.presigned_put_url(key, settings.upload_url_ttl_seconds),
        expires_in=settings.upload_url_ttl_seconds,
    )


@router.post("/{asset_id}/complete", response_model=SourceAssetResponse)
def complete_upload(
    asset_id: uuid.UUID,
    payload: UploadCompleteRequest,
    user: CurrentUser,
    session: SessionDep,
    storage: ObjectStorage = StorageDep,
) -> SourceAsset:
    """업로드 완료를 검증합니다.

    같은 키를 덮어쓸 수 있으므로 파일이 실제로 있는지, 크기가 신고한 값과 같은지
    확인한 뒤에만 uploaded로 둡니다. 형식과 길이는 워커가 ffprobe로 검사합니다.
    """
    asset = _get_asset(session, asset_id)
    info = storage.head(asset.storage_key)
    if info is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="저장소에서 업로드된 파일을 찾을 수 없습니다.",
        )
    if asset.byte_size is not None and info.byte_size != asset.byte_size:
        asset.upload_state = "rejected"
        asset.probe_error = (
            f"업로드 크기가 다릅니다. 신고 {asset.byte_size} 바이트, 실제 {info.byte_size} 바이트"
        )
        # 거부 사유를 먼저 확정합니다. 예외를 그냥 던지면 요청 트랜잭션이 롤백되어
        # 관리화면에 이유가 남지 않습니다.
        session.commit()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=asset.probe_error)

    asset.checksum = payload.checksum or info.checksum
    asset.upload_state = "uploaded"
    session.flush()

    # 실행 요청 기록과 큐 전달을 한 트랜잭션으로 묶습니다.
    enqueue(
        session,
        topic="source_asset.verify",
        payload={"source_asset_id": str(asset.id)},
        dedupe_key=f"source_asset.verify:{asset.id}",
    )
    return asset


@router.get("", response_model=list[SourceAssetResponse])
def list_assets(user: CurrentUser, session: SessionDep, limit: int = 50) -> list[SourceAsset]:
    stmt = select(SourceAsset).order_by(SourceAsset.created_at.desc()).limit(min(limit, 200))
    return list(session.scalars(stmt))


@router.get("/{asset_id}", response_model=SourceAssetResponse)
def get_asset(asset_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> SourceAsset:
    return _get_asset(session, asset_id)


@router.get("/{asset_id}/preview-url", response_model=PreviewUrlResponse)
def preview_url(
    asset_id: uuid.UUID,
    user: CurrentUser,
    session: SessionDep,
    storage: ObjectStorage = StorageDep,
    settings: Settings = SettingsDep,
) -> PreviewUrlResponse:
    """미리보기 URL은 API만 발급합니다. 저장소는 비공개로 둡니다."""
    asset = _get_asset(session, asset_id)
    if asset.upload_state == "awaiting_upload":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="아직 업로드가 끝나지 않았습니다."
        )
    return PreviewUrlResponse(
        url=storage.presigned_get_url(asset.storage_key, settings.preview_url_ttl_seconds),
        expires_in=settings.preview_url_ttl_seconds,
    )


def _get_asset(session, asset_id: uuid.UUID) -> SourceAsset:  # noqa: ANN001
    asset = session.get(SourceAsset, asset_id)
    if asset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="원본을 찾을 수 없습니다."
        )
    return asset
