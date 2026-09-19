"""Workflow controls, explicit budget configuration, and publication requests."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, Field, ValidationError, model_validator
from sqlalchemy import select

from adminapi.config import get_settings
from adminapi.deps import CurrentUser, SessionDep
from adminapi.models import (
    Approval,
    Artifact,
    Budget,
    BudgetReservation,
    Job,
    Publication,
    StageRun,
    utcnow,
)
from adminapi.outbox import enqueue
from adminapi.services.budget import held_total, release, settle
from adminapi.subtitle_rules import subtitle_rules
from pipeline.editing import Cue
from pipeline.states import JobState, PublicationState, StageRunState, assert_transition
from pipeline.subtitle_files import MEDIA_TYPES, SubtitleFormat, subtitle_file
from pipeline.time import as_utc
from pipeline.workflow import WorkflowOptions, rendered_cues, rendered_language

router = APIRouter(tags=["workflow"])


def get_job(session, job_id):
    job = session.scalar(select(Job).where(Job.id == job_id).with_for_update())
    if job is None:
        raise HTTPException(404, "작업을 찾을 수 없습니다.")
    return job


def ensure_idle(job):
    if job.lease_until and as_utc(job.lease_until) > utcnow():
        raise HTTPException(409, "단계가 실행 중입니다. 완료 후 다시 시도하세요.")


@router.get("/workflow/configuration")
def configuration(user: CurrentUser):
    s = get_settings()
    return {
        "paid_enabled": s.paid_processing_enabled,
        "translation_configured": bool(s.google_cloud_project and s.translate_usd_per_1k_chars),
        "speech_configured": bool(s.elevenlabs_api_key and s.tts_usd_per_1k_chars),
        "lipsync_configured": bool(s.sync_api_key and s.lipsync_usd_per_second),
        "youtube_configured": bool(
            s.youtube_upload_enabled and s.youtube_credentials_file and s.youtube_channel_id
        ),
        "youtube_channel_id": s.youtube_channel_id,
    }


@router.get("/jobs/{job_id}/workflow")
def detail(job_id: uuid.UUID, user: CurrentUser, session: SessionDep):
    job = get_job(session, job_id)
    stages = list(
        session.scalars(
            select(StageRun).where(StageRun.job_id == job_id).order_by(StageRun.created_at)
        )
    )
    artifact_id = job.workflow_data.get("artifact_id")
    approval = (
        session.scalar(select(Approval).where(Approval.artifact_id == uuid.UUID(artifact_id)))
        if artifact_id
        else None
    )
    return {
        "id": str(job.id),
        "state": job.state,
        "stage": job.current_stage,
        "reason": job.state_reason,
        "options": job.workflow_config,
        "artifact_id": artifact_id,
        "approval_id": str(approval.id) if approval else None,
        "cues": job.workflow_data.get("cues", []),
        "translated": job.workflow_data.get("translated", []),
        "stages": [
            {
                "id": str(s.id),
                "name": s.stage,
                "state": s.state,
                "attempt": s.attempt,
                "uncertain": bool(s.outputs.get("invoked"))
                and (not s.provider_job_id or bool(s.outputs.get("terminal_failure"))),
                "estimated_cost": s.estimated_cost,
                "error": s.error,
            }
            for s in stages
        ],
    }


@router.get("/jobs/{job_id}/subtitles")
def subtitles(
    job_id: uuid.UUID,
    user: CurrentUser,
    session: SessionDep,
    subtitle_format: SubtitleFormat = Query("srt", alias="format"),
) -> Response:
    """작업 자막을 SRT·VTT 파일로 내려줍니다.

    영상에 굽는 자막과 같습니다. 더빙 음성에 맞춰 재정렬한 자막이 있으면 그것을,
    없으면 번역본을, 번역 전이면 원본 대본을 씁니다(`rendered_cues`). 시각은 출력
    영상 시작이 0초이고, 화면 제목은 자막이 아니므로 넣지 않습니다. 렌더를
    기다리지 않고 대본 단계 뒤부터 내려받을 수 있습니다.
    """
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "작업을 찾을 수 없습니다.")
    data = job.workflow_data or {}
    rows, duration = rendered_cues(data), data.get("duration")
    if not rows or not duration:
        raise HTTPException(409, "아직 자막이 없습니다. 대본 단계를 먼저 끝내세요.")
    try:
        cues = [Cue.model_validate(row) for row in rows]
    except ValidationError:
        raise HTTPException(
            409, "저장된 자막을 읽을 수 없습니다. 작업 기록을 확인하세요."
        ) from None
    # 렌더와 같은 언어 규칙을 씁니다. 언어마다 줄 길이·읽기 속도 지침이 달라
    # 다른 규칙으로 계산하면 화면 자막과 줄이 달라집니다.
    language = rendered_language(data, WorkflowOptions.model_validate(job.workflow_config))
    text = subtitle_file(cues, 0, float(duration), subtitle_format, subtitle_rules(language))
    if not text.strip():
        raise HTTPException(409, "내보낼 자막이 없습니다.")
    name = (
        f"job-{job_id}.{language}.{subtitle_format}"
        if language
        else f"job-{job_id}.{subtitle_format}"
    )
    return Response(
        content=text,
        media_type=f"{MEDIA_TYPES[subtitle_format]}; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.post("/jobs/{job_id}/resume", status_code=202)
def resume(job_id: uuid.UUID, user: CurrentUser, session: SessionDep):
    job = get_job(session, job_id)
    ensure_idle(job)
    if job.state not in (JobState.BLOCKED, JobState.FAILED, JobState.PROCESSING):
        raise HTTPException(409, "멈춘 작업만 재개할 수 있습니다.")
    uncertain = session.scalars(
        select(StageRun).where(
            StageRun.job_id == job_id,
            StageRun.state.in_([StageRunState.RUNNING, StageRunState.FAILED]),
        )
    )
    if any(
        s.outputs.get("invoked") and (not s.provider_job_id or s.outputs.get("terminal_failure"))
        for s in uncertain
    ):
        raise HTTPException(409, "공급자 호출 결과를 먼저 확인·정산하세요.")
    job.state = assert_transition(job.state, "resume")
    job.state_reason = None
    job.lease_token = job.lease_until = None
    enqueue(
        session,
        topic="job.step",
        payload={"job_id": str(job.id)},
        dedupe_key=f"resume:{job.id}:{uuid.uuid4()}",
    )
    return {"state": job.state}


class Resolution(BaseModel):
    outcome: Literal["confirmed_not_executed", "confirmed_no_charge", "charged_without_result"]
    note: str = Field(min_length=5, max_length=1000)


@router.post("/jobs/{job_id}/stages/{stage_id}/resolve")
def resolve(
    job_id: uuid.UUID,
    stage_id: uuid.UUID,
    payload: Resolution,
    user: CurrentUser,
    session: SessionDep,
):
    job = get_job(session, job_id)
    ensure_idle(job)
    stage = session.get(StageRun, stage_id)
    if (
        stage is None
        or stage.job_id != job_id
        or not stage.outputs.get("invoked")
        or (stage.provider_job_id and not stage.outputs.get("terminal_failure"))
    ):
        raise HTTPException(409, "확인 대상 유료 호출이 아닙니다.")
    for hold in session.scalars(
        select(BudgetReservation).where(BudgetReservation.stage_run_id == stage.id)
    ):
        if payload.outcome in ("confirmed_not_executed", "confirmed_no_charge"):
            release(session, hold.id)
        else:
            settle(session, hold.id, None)
    stage.outputs = {
        "resolution": payload.outcome,
        "previous_provider_job_id": stage.provider_job_id,
        "previous_outputs": stage.outputs,
        "note": payload.note,
        "resolved_by": str(user.id),
    }
    stage.state = StageRunState.FAILED
    return {"resolved": True, "next": "resume"}


class MonthlyBudgetRequest(BaseModel):
    limit_usd: Decimal = Field(gt=0, le=100000, decimal_places=4)


@router.put("/workflow/monthly-budget")
def monthly_budget(payload: MonthlyBudgetRequest, user: CurrentUser, session: SessionDep):
    now = utcnow()
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end = (
        start.replace(year=start.year + 1, month=1)
        if start.month == 12
        else start.replace(month=start.month + 1)
    )
    budget = session.scalar(
        select(Budget)
        .where(
            Budget.scope == "monthly", Budget.scope_ref == "global", Budget.period_start == start
        )
        .with_for_update()
    )
    if budget is None:
        budget = Budget(
            scope="monthly",
            scope_ref="global",
            period_start=start,
            period_end=end,
            limit_amount=payload.limit_usd,
        )
        session.add(budget)
        session.flush()
    else:
        budget.limit_amount = payload.limit_usd
    return {
        "id": str(budget.id),
        "limit": budget.limit_amount,
        "spent": budget.spent_amount,
        "held": held_total(session, budget.id),
    }


@router.put("/jobs/{job_id}/budget")
def job_budget(
    job_id: uuid.UUID, payload: MonthlyBudgetRequest, user: CurrentUser, session: SessionDep
):
    get_job(session, job_id)
    budget = session.scalar(
        select(Budget)
        .where(Budget.scope == "job", Budget.scope_ref == str(job_id))
        .with_for_update()
    )
    if budget is None:
        raise HTTPException(404, "작업 예산이 없습니다.")
    budget.limit_amount = payload.limit_usd
    return {
        "limit": budget.limit_amount,
        "spent": budget.spent_amount,
        "held": held_total(session, budget.id),
    }


class PublicationRequest(BaseModel):
    artifact_id: uuid.UUID
    title: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=5000)
    publish_at: datetime
    made_for_kids: bool

    @model_validator(mode="after")
    def future(self):
        if self.publish_at.tzinfo is None or self.publish_at <= utcnow():
            raise ValueError("예약 시각에는 시간대가 포함되어야 하며 미래여야 합니다.")
        return self


def publication_response(row):
    return {
        "id": str(row.id),
        "state": row.state,
        "video_id": row.youtube_video_id,
        "publish_at": row.scheduled_at_utc,
        "title": row.metadata_snapshot.get("title"),
        "error": row.error,
    }


@router.post("/publications", status_code=202)
def create_publication(payload: PublicationRequest, user: CurrentUser, session: SessionDep):
    settings = get_settings()
    if not settings.youtube_channel_id:
        raise HTTPException(409, "서버의 YouTube 채널을 먼저 설정하세요.")
    artifact = session.scalar(
        select(Artifact).where(Artifact.id == payload.artifact_id).with_for_update()
    )
    if artifact is None or not artifact.checksum:
        raise HTTPException(409, "검증된 결과물이 필요합니다.")
    approval = session.scalar(select(Approval).where(Approval.artifact_id == artifact.id))
    if approval is None:
        raise HTTPException(409, "이 결과물 버전의 승인이 필요합니다.")
    existing = session.scalar(
        select(Publication).where(
            Publication.approval_id == approval.id,
            Publication.channel_id == settings.youtube_channel_id,
        )
    )
    if existing:
        if existing.metadata_snapshot != {
            "title": payload.title,
            "description": payload.description,
            "made_for_kids": payload.made_for_kids,
            "checksum": artifact.checksum,
        } or as_utc(existing.scheduled_at_utc) != payload.publish_at.astimezone(UTC):
            raise HTTPException(
                409, "이미 다른 예약 설정이 저장되어 있습니다. 중복 업로드하지 않습니다."
            )
        return publication_response(existing)
    row = Publication(
        approval_id=approval.id,
        channel_id=settings.youtube_channel_id,
        scheduled_at_utc=payload.publish_at.astimezone(UTC),
        metadata_snapshot={
            "title": payload.title,
            "description": payload.description,
            "made_for_kids": payload.made_for_kids,
            "checksum": artifact.checksum,
        },
    )
    session.add(row)
    session.flush()
    enqueue(
        session,
        topic="publication.run",
        payload={"publication_id": str(row.id)},
        dedupe_key=f"publication:{row.id}",
    )
    return publication_response(row)


@router.get("/publications")
def publications(user: CurrentUser, session: SessionDep):
    return [
        publication_response(r)
        for r in session.scalars(
            select(Publication).order_by(Publication.created_at.desc()).limit(100)
        )
    ]


@router.post("/publications/{publication_id}/resume", status_code=202)
def resume_publication(publication_id: uuid.UUID, user: CurrentUser, session: SessionDep):
    row = session.scalar(
        select(Publication).where(Publication.id == publication_id).with_for_update()
    )
    if row is None:
        raise HTTPException(404, "게시 요청이 없습니다.")
    if row.state in (PublicationState.PUBLISHED, PublicationState.CANCELLED):
        raise HTTPException(409, "종료된 요청입니다.")
    if row.lease_until and as_utc(row.lease_until) > utcnow():
        raise HTTPException(409, "처리 중입니다.")
    if (
        row.checkpoint.get("started")
        and not row.checkpoint.get("session_uri")
        and not row.youtube_video_id
    ):
        raise HTTPException(409, "업로드 세션 결과가 불명확합니다. 채널 확인이 필요합니다.")
    row.error = None
    row.lease_token = row.lease_until = None
    if row.state == PublicationState.FAILED:
        row.state = PublicationState.PENDING
    enqueue(
        session,
        topic="publication.run",
        payload={"publication_id": str(row.id)},
        dedupe_key=f"publication:{row.id}:{uuid.uuid4()}",
    )
    return publication_response(row)


class RescheduleRequest(BaseModel):
    publish_at: datetime

    @model_validator(mode="after")
    def future(self):
        if self.publish_at.tzinfo is None or self.publish_at <= utcnow():
            raise ValueError("시간대를 포함한 미래 예약 시각이 필요합니다.")
        return self


@router.post("/publications/{publication_id}/reschedule", status_code=202)
def reschedule_publication(
    publication_id: uuid.UUID, payload: RescheduleRequest, user: CurrentUser, session: SessionDep
):
    row = session.scalar(
        select(Publication).where(Publication.id == publication_id).with_for_update()
    )
    if row is None:
        raise HTTPException(404, "게시 요청이 없습니다.")
    if row.state != PublicationState.FAILED:
        raise HTTPException(409, "실패한 예약만 이 경로에서 수정할 수 있습니다.")
    ensure_idle(row)
    if (
        row.checkpoint.get("started")
        and not row.checkpoint.get("session_uri")
        and not row.youtube_video_id
    ):
        raise HTTPException(409, "업로드 결과가 불명확합니다. 채널을 먼저 확인하세요.")
    row.scheduled_at_utc = payload.publish_at.astimezone(UTC)
    row.state = PublicationState.PENDING
    row.error = None
    row.lease_token = row.lease_until = None
    enqueue(
        session,
        topic="publication.run",
        payload={"publication_id": str(row.id)},
        dedupe_key=f"reschedule:{row.id}:{uuid.uuid4()}",
    )
    return publication_response(row)
