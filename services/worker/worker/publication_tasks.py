"""Approval-bound YouTube publication with durable resumable upload checkpoints."""

from __future__ import annotations

import hashlib
import tempfile
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import or_, select, update

from adminapi.config import get_settings
from adminapi.db import get_session_factory
from adminapi.models import Approval, Artifact, Publication, utcnow
from adminapi.outbox import enqueue
from adminapi.storage import get_storage
from pipeline.states import PublicationState
from worker.celery_app import celery_app
from worker.youtube import UploadNeedsReview, schedule_video, upload_approved


def youtube_service():
    settings = get_settings()
    if not settings.youtube_upload_enabled:
        raise UploadNeedsReview("YouTube 업로드 실행 설정이 꺼져 있습니다.")
    if not settings.youtube_credentials_file or not settings.youtube_channel_id:
        raise UploadNeedsReview("YouTube 인증 파일과 채널 ID를 설정하세요.")
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    credentials = Credentials.from_authorized_user_file(settings.youtube_credentials_file)
    return build("youtube", "v3", credentials=credentials, cache_discovery=False)


def later(session, row, delay=30):
    enqueue(
        session,
        topic="publication.run",
        payload={"publication_id": str(row.id)},
        dedupe_key=f"publication:{row.id}:{uuid.uuid4()}",
        delay_seconds=delay,
    )


@celery_app.task(
    name="worker.publication_tasks.run_publication", soft_time_limit=3500, time_limit=3600
)
def run_publication(publication_id: str):
    factory = get_session_factory()
    pid = uuid.UUID(publication_id)
    token = str(uuid.uuid4())
    with factory() as session:
        claimed = session.execute(
            update(Publication)
            .where(
                Publication.id == pid,
                Publication.state.in_(
                    [
                        PublicationState.PENDING,
                        PublicationState.UPLOADING,
                        PublicationState.PROCESSING_ON_YOUTUBE,
                        PublicationState.SCHEDULED,
                    ]
                ),
                or_(Publication.lease_until.is_(None), Publication.lease_until < utcnow()),
            )
            .values(lease_token=token, lease_until=utcnow() + timedelta(hours=2))
        )
        session.commit()
        if not claimed.rowcount:
            return {"status": "not_runnable"}
    try:
        service = youtube_service()
        with factory() as session:
            row = session.get(Publication, pid)
            approval = session.get(Approval, row.approval_id)
            artifact = session.get(Artifact, approval.artifact_id)
            metadata = dict(row.metadata_snapshot)
            if artifact.checksum != metadata["checksum"]:
                raise UploadNeedsReview("승인된 결과물 체크섬이 변경되었습니다.")
            if row.channel_id != get_settings().youtube_channel_id:
                raise UploadNeedsReview("설정 채널이 게시 요청 당시와 다릅니다.")
            channels = service.channels().list(part="id", mine=True).execute().get("items", [])
            if row.channel_id not in [item["id"] for item in channels]:
                raise UploadNeedsReview("OAuth 계정의 채널이 지정된 채널과 다릅니다.")
            video_id = row.youtube_video_id
            checkpoint = dict(row.checkpoint)
            scheduled = row.scheduled_at_utc.replace(tzinfo=UTC)
            if not video_id:
                if scheduled <= utcnow():
                    raise UploadNeedsReview("예약 시각이 지났습니다. 새 예약 요청을 준비하세요.")
                row.state = PublicationState.UPLOADING
                session.commit()

        def save(checkpoint):
            with factory() as session:
                current = session.scalar(
                    select(Publication).where(Publication.id == pid).with_for_update()
                )
                if current.lease_token != token:
                    raise UploadNeedsReview("게시 작업의 실행 권한이 만료되었습니다.")
                current.checkpoint = checkpoint
                current.upload_session_url = checkpoint.get("session_uri")
                current.youtube_video_id = checkpoint.get("video_id")
                session.commit()

        if not video_id:
            with tempfile.TemporaryDirectory(prefix="r4-upload-") as directory:
                path = Path(directory) / "approved.mp4"
                get_storage().download_file(artifact.storage_key, path)
                with path.open("rb") as stream:
                    checksum = hashlib.file_digest(stream, "sha256").hexdigest()
                if checksum != metadata["checksum"]:
                    raise UploadNeedsReview(
                        "저장소 파일이 승인된 파일과 다릅니다. 업로드하지 않았습니다."
                    )
                video_id = upload_approved(
                    service,
                    path,
                    approval_id=str(approval.id),
                    title=metadata["title"],
                    description=metadata["description"],
                    checkpoint=checkpoint,
                    save=save,
                    made_for_kids=metadata["made_for_kids"],
                    allow_upload=True,
                )
        response = (
            service.videos().list(part="snippet,status,processingDetails", id=video_id).execute()
        )
        items = response.get("items", [])
        if not items:
            raise UploadNeedsReview("YouTube 영상을 조회할 수 없습니다.")
        info = items[0]
        if info.get("snippet", {}).get("channelId") != row.channel_id:
            raise UploadNeedsReview("조회한 영상의 채널이 다릅니다.")
        state = info.get("status", {})
        processing = info.get("processingDetails", {}).get("processingStatus")
        delay = 30
        if state.get("privacyStatus") == "public":
            final_state = PublicationState.PUBLISHED
        elif processing in ("failed", "terminated") or state.get("uploadStatus") in (
            "failed",
            "rejected",
            "deleted",
        ):
            raise UploadNeedsReview("YouTube 영상 처리가 실패했습니다. 채널에서 사유를 확인하세요.")
        elif processing != "succeeded":
            if scheduled <= utcnow():
                raise UploadNeedsReview("YouTube 처리 중 예약 시각이 지났습니다.")
            final_state = PublicationState.PROCESSING_ON_YOUTUBE
        else:
            requested = state.get("publishAt")
            matches = (
                requested and datetime.fromisoformat(requested.replace("Z", "+00:00")) == scheduled
            )
            if not matches:
                schedule_video(
                    service, video_id, scheduled, made_for_kids=metadata["made_for_kids"]
                )
                confirmed = (
                    service.videos().list(part="status", id=video_id).execute().get("items", [])
                )
                value = confirmed[0].get("status", {}).get("publishAt") if confirmed else None
                if not value or datetime.fromisoformat(value.replace("Z", "+00:00")) != scheduled:
                    raise UploadNeedsReview(
                        "예약 응답을 확인하지 못했습니다. 기존 영상을 다시 조회하세요."
                    )
            final_state = PublicationState.SCHEDULED
            delay = max(30, min(3600, int((scheduled - utcnow()).total_seconds())))
        with factory() as session:
            row = session.scalar(select(Publication).where(Publication.id == pid).with_for_update())
            if row.lease_token != token:
                return {"status": "stale"}
            row.youtube_video_id = video_id
            row.state = final_state
            row.error = None
            row.lease_token = row.lease_until = None
            if final_state != PublicationState.PUBLISHED:
                later(session, row, delay)
            session.commit()
        return {"status": final_state.value}
    except Exception as exc:
        with factory() as session:
            row = session.get(Publication, pid)
            if row.lease_token == token:
                row.state = PublicationState.FAILED
                row.error = (
                    str(exc)
                    if isinstance(exc, UploadNeedsReview | ValueError)
                    else f"{type(exc).__name__}: 게시 실패. 기존 세션을 보존했습니다."
                )
                row.lease_token = row.lease_until = None
                session.commit()
        return {"status": "failed"}
