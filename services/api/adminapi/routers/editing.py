"""Transcript import, clip editing, local analysis and immutable artifact approval."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from adminapi.deps import CurrentUser, SessionDep
from adminapi.models import (
    Approval,
    Artifact,
    ClipEdit,
    ClipRange,
    MediaTask,
    SourceAsset,
    TranscriptSegment,
)
from adminapi.outbox import enqueue
from adminapi.storage import ObjectStorage, get_storage
from pipeline.editing import Cue, EditSpec, suggest_clips

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
    return {"version": version, "count": len(payload.cues)}


class AnalysisRequest(BaseModel):
    kind: Literal["transcribe", "scenes"]
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
        and (datetime.now(UTC) - task.started_at.replace(tzinfo=UTC)).total_seconds() > 7200
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
    existing = session.scalar(
        select(Approval).where(Approval.artifact_id == artifact_id, Approval.metadata_version == 1)
    )
    if existing is None:
        existing = Approval(artifact_id=artifact.id, approver_id=user.id)
        session.add(existing)
        session.flush()
    return {"approval_id": str(existing.id), "artifact_id": str(artifact.id)}
