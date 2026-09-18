"""작업 생성·목록·상태."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from adminapi.deps import CurrentUser, SessionDep
from adminapi.models import Job, SourceAsset
from adminapi.outbox import enqueue
from adminapi.schemas import JobCreateRequest, JobResponse, JobTransitionRequest
from pipeline.states import JobState, TransitionError, assert_transition

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

    job = Job(
        source_asset_id=asset.id,
        target_language=payload.target_language,
        state=JobState.QUEUED,
        created_by_id=user.id,
    )
    session.add(job)
    session.flush()
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
    try:
        job.state = assert_transition(job.state, payload.event)
    except TransitionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from None
    job.state_reason = payload.reason
    session.flush()
    return job


def _get_job(session, job_id: uuid.UUID) -> Job:  # noqa: ANN001
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="작업을 찾을 수 없습니다."
        )
    return job
