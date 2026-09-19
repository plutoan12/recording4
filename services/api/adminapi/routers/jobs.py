"""작업 생성·목록·상태."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from adminapi.deps import CurrentUser, SessionDep
from adminapi.models import Budget, Job, SourceAsset, VoiceAssignment, utcnow
from adminapi.outbox import enqueue
from adminapi.schemas import JobCreateRequest, JobResponse, JobTransitionRequest
from pipeline.states import JobState, TransitionError, assert_transition
from pipeline.time import as_utc

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("", response_model=JobResponse, status_code=status.HTTP_201_CREATED)
def create_job(payload: JobCreateRequest, user: CurrentUser, session: SessionDep) -> Job:
    asset = session.get(SourceAsset, payload.source_asset_id)
    if asset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="원본을 찾을 수 없습니다."
        )
    if asset.upload_state != "verified":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"검사를 통과한 원본만 작업을 만들 수 있습니다. 현재 상태: {asset.upload_state}",
        )

    if (
        payload.workflow.clip
        and asset.duration_seconds is not None
        and payload.workflow.clip.end > float(asset.duration_seconds)
    ):
        raise HTTPException(422, "선택 구간이 원본 길이를 넘습니다.")
    if payload.workflow.reuse_from_job_id:
        parent = session.get(Job, payload.workflow.reuse_from_job_id)
        if parent is None or parent.created_by_id != user.id or parent.source_asset_id != asset.id:
            raise HTTPException(422, "같은 사용자의 동일 원본 작업만 음성을 재사용할 수 있습니다.")
    job = Job(
        source_asset_id=asset.id,
        target_language=payload.target_language,
        workflow_config=payload.workflow.model_dump(mode="json"),
        state=JobState.QUEUED,
        created_by_id=user.id,
    )
    session.add(job)
    session.flush()
    session.add(
        Budget(scope="job", scope_ref=str(job.id), limit_amount=payload.workflow.budget_usd)
    )
    enqueue(
        session,
        topic="job.start",
        payload={"job_id": str(job.id)},
        dedupe_key=f"job.start:{job.id}:{job.settings_version}",
    )
    return job


@router.get("", response_model=list[JobResponse])
def list_jobs(
    user: CurrentUser,
    session: SessionDep,
    state: JobState | None = Query(default=None),
    limit: int = Query(default=50, le=200),
) -> list[Job]:
    stmt = select(Job).order_by(Job.created_at.desc()).limit(limit)
    if state is not None:
        stmt = stmt.where(Job.state == state)
    return list(session.scalars(stmt))


@router.get("/{job_id}", response_model=JobResponse)
def get_job(job_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> Job:
    return _get_job(session, job_id)


@router.post("/{job_id}/transitions", response_model=JobResponse)
def transition(
    job_id: uuid.UUID, payload: JobTransitionRequest, user: CurrentUser, session: SessionDep
) -> Job:
    """전이표에 있는 전이만 허용합니다."""
    job = _get_job(session, job_id)
    if payload.event not in ("cancel", "reject"):
        raise HTTPException(
            409, "허용되지 않은 전이입니다. 단계 실행·결과물 승인 API를 사용하세요."
        )
    if job.lease_until and as_utc(job.lease_until) > utcnow():
        raise HTTPException(409, "실행 중인 단계가 끝난 뒤 상태를 변경하세요.")
    try:
        job.state = assert_transition(job.state, payload.event)
    except TransitionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from None
    job.state_reason = payload.reason
    session.flush()
    return job


class VoiceAssignmentRequest(BaseModel):
    """화자 표시 → 공급자 음성 ID. 화자 분리 결과를 실제 음성에 연결합니다."""

    assignments: dict[str, str] = Field(min_length=1, max_length=20)


@router.get("/{job_id}/voice-assignments")
def get_voice_assignments(job_id: uuid.UUID, user: CurrentUser, session: SessionDep):
    """최신 버전의 화자별 음성 배정을 돌려줍니다."""
    _get_job(session, job_id)
    version = session.scalar(
        select(func.max(VoiceAssignment.version)).where(VoiceAssignment.job_id == job_id)
    )
    rows = (
        list(
            session.scalars(
                select(VoiceAssignment).where(
                    VoiceAssignment.job_id == job_id, VoiceAssignment.version == version
                )
            )
        )
        if version
        else []
    )
    return {
        "version": version,
        "assignments": {row.speaker: row.provider_voice_id for row in rows},
    }


@router.put("/{job_id}/voice-assignments")
def put_voice_assignments(
    job_id: uuid.UUID,
    payload: VoiceAssignmentRequest,
    user: CurrentUser,
    session: SessionDep,
):
    """음성 배정을 새 버전으로 저장합니다. 기존 버전은 감사용으로 남깁니다.

    화자 표시는 화자 분리가 만든 값(`SPEAKER_00` 등)이나 `default`입니다.
    어떤 음성을 쓸지는 사람이 고릅니다. 여기서 추측하지 않습니다.
    """
    _get_job(session, job_id)
    for speaker, voice in payload.assignments.items():
        if not speaker.strip() or not voice.strip():
            raise HTTPException(422, "화자 표시와 음성 ID는 비어 있을 수 없습니다.")
        if len(speaker) > 64 or len(voice) > 128:
            raise HTTPException(422, "화자 표시 또는 음성 ID가 너무 깁니다.")
    version = (
        session.scalar(
            select(func.max(VoiceAssignment.version)).where(VoiceAssignment.job_id == job_id)
        )
        or 0
    ) + 1
    session.add_all(
        [
            VoiceAssignment(
                job_id=job_id, speaker=speaker, provider_voice_id=voice, version=version
            )
            for speaker, voice in payload.assignments.items()
        ]
    )
    return {"version": version, "count": len(payload.assignments)}


def _get_job(session, job_id: uuid.UUID) -> Job:  # noqa: ANN001
    job = session.scalar(select(Job).where(Job.id == job_id).with_for_update())
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="작업을 찾을 수 없습니다."
        )
    return job
