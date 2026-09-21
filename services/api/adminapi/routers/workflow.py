"""Workflow controls, explicit budget configuration, and publication requests."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select

from adminapi.artifact_subtitles import Missing, job_subtitles
from adminapi.config import get_settings
from adminapi.deps import CurrentUser, SessionDep
from adminapi.models import (
    Approval,
    Artifact,
    Budget,
    BudgetReservation,
    Glossary,
    Job,
    Publication,
    StageRun,
    SubtitleReview,
    utcnow,
)
from adminapi.outbox import enqueue
from adminapi.services.budget import held_total, release, settle
from pipeline.languages import LANGUAGES, catalogue
from pipeline.review import branch_for, subtitle_path
from pipeline.states import JobState, PublicationState, StageRunState, assert_transition
from pipeline.style_review import style_warnings
from pipeline.subtitle_files import MEDIA_TYPES, SubtitleFormat
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


def github_ready(s) -> bool:
    """GitHub 저장소 검수가 돌 수 있는지. 셋 다 있어야 브랜치·커밋·PR을 만듭니다."""
    return bool(s.github_review_enabled and s.github_token and s.github_repository)


def translation_ready(s) -> bool:
    """설정한 공급자로 번역이 돌 수 있는지. 로컬 모델은 키가 필요 없습니다."""
    if s.translation_provider == "google":
        return bool(s.google_cloud_project and s.translate_usd_per_1k_chars)
    if s.translation_provider == "deepl":
        return bool(s.deepl_api_key and s.translate_usd_per_1k_chars)
    return s.translation_provider == "huggingface"


@router.get("/workflow/configuration")
def configuration(user: CurrentUser):
    s = get_settings()
    return {
        "paid_enabled": s.paid_processing_enabled,
        "translation_provider": s.translation_provider,
        "translation_configured": translation_ready(s),
        "translation_refine_enabled": bool(
            s.translation_refine_enabled and s.refine_usd_per_1k_chars
        ),
        "speech_configured": bool(s.elevenlabs_api_key and s.tts_usd_per_1k_chars),
        "lipsync_configured": bool(s.sync_api_key and s.lipsync_usd_per_second),
        "youtube_configured": bool(
            s.youtube_upload_enabled and s.youtube_credentials_file and s.youtube_channel_id
        ),
        "youtube_channel_id": s.youtube_channel_id,
        "youtube_captions_enabled": s.youtube_captions_enabled,
        "github_review_configured": github_ready(s),
        "github_repository": s.github_repository,
        # 언어와 번역 방향은 pipeline.languages 한 곳에서 옵니다. 화면은 이것만 봅니다.
        **catalogue(),
    }


LANGUAGE_OR_ANY = r"^(\*|[a-z]{2,3})$"


class GlossaryRequest(BaseModel):
    source_language: str = Field(pattern=LANGUAGE_OR_ANY)
    target_language: str = Field(pattern=LANGUAGE_OR_ANY)
    # 원문 → 목표 표기. 비어 있으면 원문 그대로 지킵니다(인명·그룹명·곡명·브랜드명).
    entries: dict[str, str | None] = Field(max_length=5000)

    @model_validator(mode="after")
    def known_languages(self):
        for code in (self.source_language, self.target_language):
            if code != "*" and code not in LANGUAGES:
                raise ValueError(f"지원하지 않는 언어입니다: {code}")
        if any(not term.strip() or len(term) > 200 for term in self.entries):
            raise ValueError("용어는 비어 있지 않고 200자 이하여야 합니다.")
        return self


def latest_glossary(session, source, target):
    return session.scalar(
        select(Glossary)
        .where(
            Glossary.scope == "project",
            Glossary.source_language == source,
            Glossary.target_language == target,
        )
        .order_by(Glossary.version.desc())
    )


def glossary_response(row, source, target):
    return {
        "source_language": source,
        "target_language": target,
        "version": row.version if row else 0,
        "entries": row.entries if row else {},
    }


@router.get("/workflow/glossary")
def get_glossary(
    user: CurrentUser,
    session: SessionDep,
    source: str = Query(default="*", pattern=LANGUAGE_OR_ANY),
    target: str = Query(default="*", pattern=LANGUAGE_OR_ANY),
):
    return glossary_response(latest_glossary(session, source, target), source, target)


@router.put("/workflow/glossary")
def put_glossary(payload: GlossaryRequest, user: CurrentUser, session: SessionDep):
    """새 버전을 덧붙입니다. 옛 버전으로 만든 번역 기억은 그대로 두고 다시 쓰지 않습니다."""
    previous = latest_glossary(session, payload.source_language, payload.target_language)
    row = Glossary(
        scope="project",
        source_language=payload.source_language,
        target_language=payload.target_language,
        version=(previous.version + 1) if previous else 1,
        entries=payload.entries,
    )
    session.add(row)
    session.commit()
    return glossary_response(row, payload.source_language, payload.target_language)


class ReviewRequest(BaseModel):
    kind: Literal["export", "import"]


def review_response(row, *, full: bool = False) -> dict:
    """검수 행 하나. 목록에는 자막을 싣지 않습니다(5,000개까지 올 수 있습니다)."""
    result = row.result or {}
    data = {
        "id": str(row.id),
        "job_id": str(row.job_id),
        "kind": row.kind,
        "state": row.state,
        "language": row.language,
        "branch": row.branch,
        "path": row.path,
        "pull_number": row.pull_number,
        "pull_url": row.pull_url,
        "error": row.error,
        "problems": result.get("problems", []),
        "notes": result.get("notes", []),
        "applicable": bool(result.get("applicable")),
        "glossary_changed": bool(result.get("glossary_changed")),
        "cue_count": result.get("cue_count", 0),
    }
    if full:
        data["cues"] = result.get("cues", [])
        data["glossary"] = result.get("glossary")
        data["glossary_source"] = result.get("source_language") or "*"
    return data


def latest_export(session, job_id):  # noqa: ANN001
    return session.scalar(
        select(SubtitleReview)
        .where(
            SubtitleReview.job_id == job_id,
            SubtitleReview.kind == "export",
            SubtitleReview.state == "succeeded",
        )
        .order_by(SubtitleReview.created_at.desc())
    )


@router.post("/jobs/{job_id}/review", status_code=202)
def start_review(job_id: uuid.UUID, payload: ReviewRequest, user: CurrentUser, session: SessionDep):
    """자막 검수를 GitHub 저장소로 내보내거나, 거기서 고친 것을 가져옵니다.

    가져온 번역은 작업에 자동으로 들어가지 않습니다. 화면에서 문제를 확인한 뒤
    기존 "새 버전 만들기" 경로로 사람이 넣습니다. 병합도 사람이 합니다.
    """
    job = get_job(session, job_id)
    ensure_idle(job)
    settings = get_settings()
    if not github_ready(settings):
        raise HTTPException(
            409, "GitHub 검수 설정(R4_GITHUB_REVIEW_ENABLED·토큰·저장소)을 먼저 켜세요."
        )
    options = WorkflowOptions.model_validate(job.workflow_config)
    if payload.kind == "export":
        if not rendered_cues(job.workflow_data or {}):
            raise HTTPException(409, "아직 자막이 없습니다. 대본·번역 단계를 먼저 끝내세요.")
        language = rendered_language(job.workflow_data, options) or job.target_language
        row = SubtitleReview(
            job_id=job.id,
            kind="export",
            language=language,
            branch=branch_for(str(job.id)),
            path=subtitle_path(str(job.id), language),
        )
    else:
        exported = latest_export(session, job.id)
        if exported is None:
            raise HTTPException(409, "먼저 내보내기를 해서 검수 브랜치를 만드세요.")
        row = SubtitleReview(
            job_id=job.id,
            kind="import",
            language=exported.language,
            branch=exported.branch,
            path=exported.path,
            pull_number=exported.pull_number,
            pull_url=exported.pull_url,
            result={"glossary_path": (exported.result or {}).get("glossary_path")},
        )
    session.add(row)
    session.flush()
    enqueue(
        session,
        topic="review.run",
        payload={"review_id": str(row.id)},
        dedupe_key=f"review.run:{row.id}",
    )
    session.commit()
    return review_response(row)


@router.get("/jobs/{job_id}/reviews")
def reviews(job_id: uuid.UUID, user: CurrentUser, session: SessionDep):
    rows = session.scalars(
        select(SubtitleReview)
        .where(SubtitleReview.job_id == job_id)
        .order_by(SubtitleReview.created_at.desc())
        .limit(20)
    )
    return [review_response(row) for row in rows]


@router.get("/reviews/{review_id}")
def review_detail(review_id: uuid.UUID, user: CurrentUser, session: SessionDep):
    row = session.get(SubtitleReview, review_id)
    if row is None:
        raise HTTPException(404, "검수 요청을 찾을 수 없습니다.")
    return review_response(row, full=True)


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
        # 번역 QA(용어집 위반·숫자 누락). 읽기 전용이고 자동으로 고치지 않습니다.
        "translation_qa": job.workflow_data.get("translation_qa", []),
        "style_warnings": style_warnings(
            rendered_cues(job.workflow_data),
            rendered_language(
                job.workflow_data, WorkflowOptions.model_validate(job.workflow_config)
            ),
        ),
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
    found = job_subtitles(job, subtitle_format)
    if isinstance(found, Missing):
        raise HTTPException(409, found.reason)
    name = (
        f"job-{job_id}.{found.language}.{subtitle_format}"
        if found.language
        else f"job-{job_id}.{subtitle_format}"
    )
    return Response(
        content=found.text,
        media_type=f"{MEDIA_TYPES[subtitle_format]}; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{name}"',
            # 영상과 같은 규칙인지 받는 쪽이 알 수 있게 합니다. rendered면 렌더
            # 때 쓴 규칙, settings면 지금 설정(기록이 없거나 깨짐)입니다.
            "X-Subtitle-Rules": found.rules_source,
        },
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
        # 자막 트랙을 올렸는지, 건너뛰었다면 왜인지. 설정을 끈 경우에는 없습니다.
        "captions": row.checkpoint.get("captions"),
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
    from adminapi.artifact_subtitles import Missing, artifact_burns_subtitles, artifact_subtitles

    if not artifact_burns_subtitles(session, artifact):
        captions = artifact_subtitles(session, artifact, "srt")
        if (
            not settings.youtube_captions_enabled
            or isinstance(captions, Missing)
            or not captions.language
        ):
            raise HTTPException(
                409, "트랙 전용 게시에는 YouTube 자막 설정과 언어가 있는 자막이 필요합니다."
            )
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
