"""Approval-bound YouTube publication with durable resumable upload checkpoints."""

from __future__ import annotations

import hashlib
import tempfile
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import or_, select, update

from adminapi.artifact_subtitles import Missing, artifact_subtitles
from adminapi.config import get_settings
from adminapi.db import get_session_factory
from adminapi.models import Approval, Artifact, Publication, utcnow
from adminapi.outbox import enqueue
from adminapi.storage import get_storage
from pipeline.states import PublicationState
from pipeline.time import as_utc
from worker.celery_app import celery_app
from worker.youtube import UploadNeedsReview, schedule_video, upload_approved, upload_captions


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


def publish_captions(service, publication_id, video_id, artifact_id, save):
    """선택 가능한 자막 트랙을 올립니다. 영상은 이미 올라가 있으므로 막지 않습니다.

    영상에는 자막이 이미 구워져 있습니다. 트랙은 시청자가 켜고 끌 수 있는 별도
    자막이며, 설정을 켠 경우에만 올립니다.

    결과는 게시 기록(`checkpoint["captions"]`)에 남깁니다. 실패해도 게시를 실패로
    만들지 않습니다. 이미 올라간 영상을 자막 때문에 되돌릴 수는 없습니다. 대신
    무엇이 왜 안 됐는지 남겨 사람이 보고 판단하게 합니다.

    기록은 지금 저장된 값을 다시 읽어 씁니다. 부르는 쪽이 들고 있는 사본에는
    업로드 세션 값이 빠져 있어, 그대로 저장하면 영상 ID를 지웁니다.
    """
    if not get_settings().youtube_captions_enabled:
        return
    factory = get_session_factory()
    with factory() as session:
        row = session.get(Publication, publication_id)
        checkpoint = dict(row.checkpoint)
        if checkpoint.get("captions", {}).get("caption_id"):
            return
        found = artifact_subtitles(session, session.get(Artifact, artifact_id), "srt")
    try:
        if isinstance(found, Missing):
            state = {"state": "skipped", "reason": found.reason}
        elif not found.language:
            state = {"state": "skipped", "reason": "자막 언어를 몰라 트랙을 올리지 않았습니다."}
        else:
            with tempfile.TemporaryDirectory(prefix="r4-captions-") as directory:
                path = Path(directory) / "captions.srt"
                path.write_text(found.text, encoding="utf-8")
                caption_id, outcome = upload_captions(
                    service, video_id, path=path, language=found.language, allow_upload=True
                )
            state = {
                "state": outcome,
                "caption_id": caption_id,
                "language": found.language,
                "rules": found.rules_source,
            }
    except UploadNeedsReview:
        raise
    except Exception as exc:  # noqa: BLE001 - 자막 실패가 게시를 실패시키지 않습니다.
        state = {
            "state": "failed",
            "error": f"{type(exc).__name__}: 자막 트랙을 올리지 못했습니다.",
        }
    save({**checkpoint, "captions": state})


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
            scheduled = as_utc(row.scheduled_at_utc)
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
            # 처리가 끝나야 트랙을 받습니다. 예약보다 먼저 올려 공개 시점에는
            # 자막이 이미 붙어 있게 합니다.
            publish_captions(service, pid, video_id, artifact.id, save)
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
