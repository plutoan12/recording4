"""Transcript import, clip editing, local analysis and immutable artifact approval."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from adminapi.artifact_subtitles import Missing
from adminapi.artifact_subtitles import clip_subtitles as subtitles_for_clip
from adminapi.deps import CurrentUser, SessionDep
from adminapi.models import (
    Approval,
    Artifact,
    ClipEdit,
    ClipRange,
    Job,
    MediaTask,
    SourceAsset,
    TranscriptSegment,
)
from adminapi.outbox import enqueue
from adminapi.storage import ObjectStorage, get_storage
from adminapi.subtitle_rules import subtitle_rules
from pipeline.editing import Cue, EditSpec, suggest_clips
from pipeline.states import JobState
from pipeline.subtitle_files import MEDIA_TYPES, SubtitleFormat
from pipeline.subtitles import check
from pipeline.time import as_utc

router = APIRouter(tags=["editing"])


def asset_for_edit(session, asset_id):
    asset = session.scalar(select(SourceAsset).where(SourceAsset.id == asset_id).with_for_update())
    if asset is None:
        raise HTTPException(404, "원본을 찾을 수 없습니다.")
    if asset.upload_state != "verified":
        raise HTTPException(409, "검사를 통과한 원본이 필요합니다.")
    return asset


def transcript(session, asset_id):
    version = session.scalar(
        select(func.max(TranscriptSegment.transcript_version)).where(
            TranscriptSegment.source_asset_id == asset_id
        )
    )
    return list(
        session.scalars(
            select(TranscriptSegment)
            .where(
                TranscriptSegment.source_asset_id == asset_id,
                TranscriptSegment.transcript_version == version,
            )
            .order_by(TranscriptSegment.start_seconds)
        )
    )


def task_response(task):
    return {
        "id": str(task.id),
        "source_asset_id": str(task.source_asset_id),
        "clip_edit_id": str(task.clip_edit_id) if task.clip_edit_id else None,
        "kind": task.kind,
        "state": task.state,
        "result": task.result,
        "error": task.error,
        "settings": task.settings,
    }


def schedule(session, task):
    session.add(task)
    session.flush()
    enqueue(
        session,
        topic="media.run",
        payload={"task_id": str(task.id)},
        dedupe_key=f"media.run:{task.id}:{task.attempt}",
    )
    return task_response(task)


def violations(cues: list[Cue]) -> list[dict]:
    """자막 가독성 문제를 목록으로 돌려줍니다. 글자를 자동으로 고치지 않습니다."""
    return [
        {"index": v.index, "kind": v.kind, "detail": v.detail}
        for v in check(cues, subtitle_rules())
    ]


class TranscriptRequest(BaseModel):
    cues: list[Cue] = Field(min_length=1, max_length=20000)


@router.get("/source-assets/{asset_id}/transcript")
def get_transcript(asset_id: uuid.UUID, user: CurrentUser, session: SessionDep):
    asset_for_edit(session, asset_id)
    return [
        {"start": float(s.start_seconds), "end": float(s.end_seconds), "text": s.text}
        for s in transcript(session, asset_id)
    ]


@router.put("/source-assets/{asset_id}/transcript")
def put_transcript(
    asset_id: uuid.UUID, payload: TranscriptRequest, user: CurrentUser, session: SessionDep
):
    asset = asset_for_edit(session, asset_id)
    if any(c.end > float(asset.duration_seconds) for c in payload.cues):
        raise HTTPException(422, "대본 구간이 원본 길이를 넘습니다.")
    latest = transcript(session, asset_id)
    version = latest[0].transcript_version + 1 if latest else 1
    session.add_all(
        [
            TranscriptSegment(
                source_asset_id=asset_id,
                start_seconds=c.start,
                end_seconds=c.end,
                text=c.text,
                transcript_version=version,
            )
            for c in payload.cues
        ]
    )
    return {
        "version": version,
        "count": len(payload.cues),
        "violations": violations(payload.cues),
    }


class AnalysisRequest(BaseModel):
    kind: Literal["transcribe", "scenes"]
    language: str | None = Field(default=None, pattern=r"^[a-z]{2,3}$")


class DiarizeRequest(BaseModel):
    """화자 분리 요청. 화자 수를 알면 알려 주는 편이 정확합니다."""

    min_speakers: int | None = Field(default=None, ge=1, le=20)
    max_speakers: int | None = Field(default=None, ge=1, le=20)


class AlignRequest(BaseModel):
    """타이밍 없는 대본. 글자는 그대로 두고 시각만 찾습니다."""

    text: str = Field(min_length=1, max_length=50000)
    language: str | None = Field(default=None, pattern=r"^[a-z]{2,3}$")


@router.post("/source-assets/{asset_id}/analyze", status_code=202)
def analyze(asset_id: uuid.UUID, payload: AnalysisRequest, user: CurrentUser, session: SessionDep):
    asset_for_edit(session, asset_id)
    existing = session.scalar(
        select(MediaTask).where(
            MediaTask.source_asset_id == asset_id,
            MediaTask.kind == payload.kind,
            MediaTask.state.in_(["pending", "running"]),
        )
    )
    if existing:
        return task_response(existing)
    return schedule(
        session,
        MediaTask(
            source_asset_id=asset_id, kind=payload.kind, settings={"language": payload.language}
        ),
    )


@router.post("/source-assets/{asset_id}/align", status_code=202)
def align(asset_id: uuid.UUID, payload: AlignRequest, user: CurrentUser, session: SessionDep):
    """대본을 원본 오디오에 정렬해 새 대본 버전을 만듭니다. 유료 호출이 아닙니다."""
    asset_for_edit(session, asset_id)
    existing = session.scalar(
        select(MediaTask).where(
            MediaTask.source_asset_id == asset_id,
            MediaTask.kind == "align",
            MediaTask.state.in_(["pending", "running"]),
        )
    )
    if existing:
        return task_response(existing)
    return schedule(
        session,
        MediaTask(
            source_asset_id=asset_id,
            kind="align",
            settings={"text": payload.text, "language": payload.language},
        ),
    )


@router.post("/source-assets/{asset_id}/diarize", status_code=202)
def diarize(asset_id: uuid.UUID, payload: DiarizeRequest, user: CurrentUser, session: SessionDep):
    """누가 말했는지 찾아 최신 대본에 화자를 붙인 새 버전을 만듭니다."""
    asset_for_edit(session, asset_id)
    if (
        payload.min_speakers
        and payload.max_speakers
        and payload.min_speakers > payload.max_speakers
    ):
        raise HTTPException(422, "최소 화자 수가 최대 화자 수보다 큽니다.")
    if not transcript(session, asset_id):
        raise HTTPException(409, "화자를 붙일 대본이 없습니다. 먼저 전사하거나 대본을 올리세요.")
    existing = session.scalar(
        select(MediaTask).where(
            MediaTask.source_asset_id == asset_id,
            MediaTask.kind == "diarize",
            MediaTask.state.in_(["pending", "running"]),
        )
    )
    if existing:
        return task_response(existing)
    return schedule(
        session,
        MediaTask(
            source_asset_id=asset_id,
            kind="diarize",
            settings={
                "min_speakers": payload.min_speakers,
                "max_speakers": payload.max_speakers,
            },
        ),
    )


@router.get("/source-assets/{asset_id}/speakers")
def speakers(asset_id: uuid.UUID, user: CurrentUser, session: SessionDep):
    """최신 대본에 붙은 화자 목록. 화자별 발화 시간과 구간 수를 함께 봅니다."""
    asset_for_edit(session, asset_id)
    rows = transcript(session, asset_id)
    found: dict[str, dict] = {}
    for row in rows:
        if not row.speaker:
            continue
        entry = found.setdefault(row.speaker, {"speaker": row.speaker, "seconds": 0.0, "count": 0})
        entry["seconds"] += float(row.end_seconds) - float(row.start_seconds)
        entry["count"] += 1
    return {
        "version": rows[0].transcript_version if rows else None,
        "unlabeled": sum(1 for row in rows if not row.speaker),
        "speakers": sorted(found.values(), key=lambda e: (-e["seconds"], e["speaker"])),
    }


@router.get("/source-assets/{asset_id}/subtitle-check")
def subtitle_check(asset_id: uuid.UUID, user: CurrentUser, session: SessionDep):
    """저장된 최신 대본의 가독성 문제를 보고합니다."""
    asset_for_edit(session, asset_id)
    cues = [
        Cue(start=float(s.start_seconds), end=float(s.end_seconds), text=s.text)
        for s in transcript(session, asset_id)
    ]
    return {"count": len(cues), "violations": violations(cues)}


@router.get("/source-assets/{asset_id}/suggestions")
def suggestions(asset_id: uuid.UUID, user: CurrentUser, session: SessionDep):
    asset = asset_for_edit(session, asset_id)
    cues = [
        Cue(start=float(s.start_seconds), end=float(s.end_seconds), text=s.text)
        for s in transcript(session, asset_id)
    ]
    return suggest_clips(cues, duration=float(asset.duration_seconds))


class ClipRequest(EditSpec):
    source_asset_id: uuid.UUID


@router.post("/clips", status_code=202)
def create_clip(payload: ClipRequest, user: CurrentUser, session: SessionDep):
    asset = asset_for_edit(session, payload.source_asset_id)
    if payload.end > float(asset.duration_seconds):
        raise HTTPException(422, "선택 구간이 원본 길이를 넘습니다.")
    spec = EditSpec.model_validate(payload.model_dump(exclude={"source_asset_id"}))
    # Client sends its edited captions explicitly; an empty list means no captions.
    version = (
        session.scalar(
            select(func.max(ClipEdit.edit_version)).where(ClipEdit.source_asset_id == asset.id)
        )
        or 0
    ) + 1
    clip = ClipEdit(
        source_asset_id=asset.id,
        edit_version=version,
        output_language=asset.source_language or "und",
        created_by_id=user.id,
        output_width=spec.width,
        output_height=spec.height,
        screen_title=spec.title,
        publish_title=spec.title,
        subtitle_style={"font_size": spec.font_size},
    )
    session.add(clip)
    session.flush()
    session.add(
        ClipRange(
            clip_edit_id=clip.id,
            source_start_seconds=spec.start,
            source_end_seconds=spec.end,
            crop={"mode": spec.mode, "focus_x": spec.focus_x, "focus_y": spec.focus_y},
        )
    )
    return schedule(
        session,
        MediaTask(
            source_asset_id=asset.id,
            clip_edit_id=clip.id,
            kind="render",
            settings=spec.model_dump(),
        ),
    )


@router.get("/clips/{clip_edit_id}/subtitles")
def clip_subtitles(
    clip_edit_id: uuid.UUID,
    user: CurrentUser,
    session: SessionDep,
    subtitle_format: SubtitleFormat = Query("srt", alias="format"),
) -> Response:
    """편집본 자막을 SRT·VTT 파일로 내려줍니다.

    렌더할 때 쓴 표시 규칙을 그대로 거치고 시각은 클립 시작이 0초입니다. 화면
    제목은 자막이 아니므로 넣지 않습니다.

    이 기능 전에 렌더한 기록에는 그때 쓴 규칙이 남아 있지 않습니다. 그럴 때만
    지금 설정을 쓰고, 응답 헤더 `X-Subtitle-Rules`에 `settings`로 적습니다.
    설정을 그 사이에 바꿨다면 영상과 줄바꿈·분할이 다를 수 있습니다.
    """
    if session.get(ClipEdit, clip_edit_id) is None:
        raise HTTPException(404, "편집본을 찾을 수 없습니다.")
    found = subtitles_for_clip(session, clip_edit_id, subtitle_format)
    if isinstance(found, Missing):
        raise HTTPException(409, found.reason)
    return Response(
        content=found.text,
        media_type=f"{MEDIA_TYPES[subtitle_format]}; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="clip-{clip_edit_id}.{subtitle_format}"'
            ),
            # 영상과 같은 규칙인지 받는 쪽이 알 수 있게 합니다. rendered면 렌더
            # 때 쓴 규칙, settings면 지금 설정(옛 기록이라 남은 것이 없음)입니다.
            "X-Subtitle-Rules": found.rules_source,
        },
    )


@router.get("/media-tasks")
def list_tasks(user: CurrentUser, session: SessionDep):
    return [
        task_response(t)
        for t in session.scalars(select(MediaTask).order_by(MediaTask.created_at.desc()).limit(100))
    ]


@router.post("/media-tasks/{task_id}/retry", status_code=202)
def retry_task(task_id: uuid.UUID, user: CurrentUser, session: SessionDep):
    task = session.scalar(select(MediaTask).where(MediaTask.id == task_id).with_for_update())
    if task is None:
        raise HTTPException(404, "작업을 찾을 수 없습니다.")
    # A worker enforces a 1-hour hard limit. Only recover leases after 2 hours.
    stale = (
        task.state == "running"
        and task.started_at
        and (datetime.now(UTC) - as_utc(task.started_at)).total_seconds() > 7200
    )
    if task.state != "failed" and not stale:
        raise HTTPException(409, "실패하거나 2시간 이상 정체된 작업만 재시도할 수 있습니다.")
    task.state, task.error, task.started_at = "pending", None, None
    task.attempt += 1
    return schedule(session, task)


@router.get("/artifacts/{artifact_id}/preview")
def preview(
    artifact_id: uuid.UUID,
    user: CurrentUser,
    session: SessionDep,
    storage: ObjectStorage = Depends(get_storage),
):
    artifact = session.get(Artifact, artifact_id)
    if artifact is None:
        raise HTTPException(404, "결과물을 찾을 수 없습니다.")
    return {"url": storage.presigned_get_url(artifact.storage_key, 300)}


@router.post("/artifacts/{artifact_id}/approve")
def approve(artifact_id: uuid.UUID, user: CurrentUser, session: SessionDep):
    artifact = session.scalar(select(Artifact).where(Artifact.id == artifact_id).with_for_update())
    if artifact is None:
        raise HTTPException(404, "결과물을 찾을 수 없습니다.")
    if artifact.job_id:
        job = session.scalar(select(Job).where(Job.id == artifact.job_id).with_for_update())
        if job.state not in (JobState.REVIEW_REQUIRED, JobState.APPROVED) or job.workflow_data.get(
            "artifact_id"
        ) != str(artifact.id):
            raise HTTPException(409, "현재 검수 대상 결과물만 승인할 수 있습니다.")
        job.state = JobState.APPROVED
    existing = session.scalar(
        select(Approval).where(Approval.artifact_id == artifact_id, Approval.metadata_version == 1)
    )
    if existing is None:
        existing = Approval(artifact_id=artifact.id, approver_id=user.id)
        session.add(existing)
        session.flush()
    return {"approval_id": str(existing.id), "artifact_id": str(artifact.id)}
