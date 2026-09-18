"""작업 생성·목록·상태."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from adminapi.deps import CurrentUser, SessionDep
from adminapi.models import Budget, Job, SourceAsset, utcnow
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


def _get_job(session, job_id: uuid.UUID) -> Job:  # noqa: ANN001
    job = session.scalar(select(Job).where(Job.id == job_id).with_for_update())
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="작업을 찾을 수 없습니다."
        )
    return job
