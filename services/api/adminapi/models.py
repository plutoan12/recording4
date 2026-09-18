"""ORM 모델.

docs/ARCHITECTURE.md "데이터 모델 초안"과 docs/SHORT_FORM_EDITING.md "편집
데이터와 시간 처리"의 엔터티를 옮긴 것입니다. 원문 세그먼트는 원본에,
번역 세그먼트는 작업에 소속시킵니다.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from pipeline.budget import ReservationState
from pipeline.states import JobState, PublicationState, StageRunState


def utcnow() -> datetime:
    """내부 저장은 항상 UTC입니다. 화면 표시만 Asia/Seoul로 변환합니다."""
    return datetime.now(UTC)


def new_id() -> uuid.UUID:
    return uuid.uuid4()


def state_column(enum_type: type, length: int) -> Enum:
    """상태 컬럼 타입.

    DB에는 설계 문서에 적힌 소문자 값을 그대로 저장하고, 읽을 때는 열거형으로
    돌려받습니다. 문자열로 돌아오면 전이표 조회가 깨집니다.
    """
    return Enum(
        enum_type,
        native_enum=False,
        length=length,
        values_callable=lambda enum: [member.value for member in enum],
        validate_strings=True,
    )


class Base(DeclarativeBase):
    type_annotation_map = {dict: JSON, Decimal: Numeric(12, 4)}


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class User(Base, TimestampMixin):
    """관리자. 초기 가정은 관리자 1명이지만 승인자를 기록해야 하므로 테이블로 둡니다."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class SourceAsset(Base, TimestampMixin):
    """원본 영상."""

    __tablename__ = "source_assets"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    storage_key: Mapped[str] = mapped_column(String(1024), unique=True)
    original_filename: Mapped[str] = mapped_column(String(512))
    checksum: Mapped[str | None] = mapped_column(String(128), default=None)
    byte_size: Mapped[int | None] = mapped_column(Integer, default=None)
    duration_seconds: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), default=None)
    width: Mapped[int | None] = mapped_column(Integer, default=None)
    height: Mapped[int | None] = mapped_column(Integer, default=None)
    source_language: Mapped[str | None] = mapped_column(String(16), default=None)
    upload_state: Mapped[str] = mapped_column(String(32), default="awaiting_upload")
    probe_error: Mapped[str | None] = mapped_column(Text, default=None)
    created_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))

    jobs: Mapped[list[Job]] = relationship(back_populates="source_asset")

    __table_args__ = (
        CheckConstraint(
            "upload_state in ('awaiting_upload','uploaded','verified','rejected')",
            name="ck_source_assets_upload_state",
        ),
    )


class TranscriptSegment(Base, TimestampMixin):
    """원문 세그먼트. 원본에 소속되므로 언어를 추가해도 복제하지 않습니다."""

    __tablename__ = "transcript_segments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    source_asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source_assets.id", ondelete="CASCADE"), index=True
    )
    stage_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("stage_runs.id"), default=None
    )
    speaker: Mapped[str | None] = mapped_column(String(64), default=None)
    start_seconds: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    end_seconds: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    text: Mapped[str] = mapped_column(Text)
    transcript_version: Mapped[int] = mapped_column(Integer, default=1)

    __table_args__ = (
        Index("ix_transcript_segments_asset_start", "source_asset_id", "start_seconds"),
        CheckConstraint("end_seconds >= start_seconds", name="ck_transcript_segment_range"),
    )


class Job(Base, TimestampMixin):
    """작업. 원본 하나와 대상 언어 하나의 조합입니다."""

    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    source_asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("source_assets.id"), index=True)
    target_language: Mapped[str] = mapped_column(String(16))
    settings_version: Mapped[int] = mapped_column(Integer, default=1)
    current_stage: Mapped[str | None] = mapped_column(String(64), default=None)
    state: Mapped[JobState] = mapped_column(state_column(JobState, 32), default=JobState.QUEUED)
    state_reason: Mapped[str | None] = mapped_column(Text, default=None)
    created_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))

    workflow_config: Mapped[dict] = mapped_column(JSON, default=dict)
    workflow_data: Mapped[dict] = mapped_column(JSON, default=dict)
    lease_token: Mapped[str | None] = mapped_column(String(36), default=None)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    source_asset: Mapped[SourceAsset] = relationship(back_populates="jobs")
    stage_runs: Mapped[list[StageRun]] = relationship(back_populates="job")


class StageRun(Base, TimestampMixin):
    """단계 실행. 입력 해시가 같고 succeeded면 산출물을 재사용합니다."""

    __tablename__ = "stage_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), index=True, default=None
    )
    source_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("source_assets.id", ondelete="CASCADE"), index=True, default=None
    )
    stage: Mapped[str] = mapped_column(String(64))
    input_hash: Mapped[str] = mapped_column(String(64), index=True)
    reusable: Mapped[bool] = mapped_column(Boolean, default=True)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    state: Mapped[StageRunState] = mapped_column(
        state_column(StageRunState, 32), default=StageRunState.PENDING
    )
    provider: Mapped[str | None] = mapped_column(String(64), default=None)
    provider_job_id: Mapped[str | None] = mapped_column(String(255), default=None)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    estimated_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), default=None)
    actual_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), default=None)

    outputs: Mapped[dict] = mapped_column(JSON, default=dict)

    job: Mapped[Job | None] = relationship(back_populates="stage_runs")

    __table_args__ = (
        # 같은 작업·단계·입력 해시의 시도를 한 번만 만들도록 하는 중복 방지 키입니다.
        UniqueConstraint("job_id", "stage", "input_hash", "attempt", name="uq_stage_run_attempt"),
    )


class TranslatedSegment(Base, TimestampMixin):
    """번역 세그먼트. 작업에 소속되고 원문 세그먼트를 참조만 합니다."""

    __tablename__ = "translated_segments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    transcript_segment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("transcript_segments.id", ondelete="CASCADE")
    )
    text: Mapped[str] = mapped_column(Text)
    edit_version: Mapped[int] = mapped_column(Integer, default=1)
    voice_key: Mapped[str | None] = mapped_column(String(128), default=None)


class Glossary(Base, TimestampMixin):
    """용어집. 번역 단계의 입력이며 버전이 입력 해시에 들어갑니다."""

    __tablename__ = "glossaries"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    scope: Mapped[str] = mapped_column(String(32), default="project")
    source_language: Mapped[str] = mapped_column(String(16))
    target_language: Mapped[str] = mapped_column(String(16))
    version: Mapped[int] = mapped_column(Integer, default=1)
    entries: Mapped[dict] = mapped_column(JSON, default=dict)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class VoiceAssignment(Base, TimestampMixin):
    """화자별 음성 배정. 화자를 나누지 않는 작업도 기본 화자 하나로 둡니다."""

    __tablename__ = "voice_assignments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    speaker: Mapped[str] = mapped_column(String(64), default="default")
    provider_voice_id: Mapped[str] = mapped_column(String(128))
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    version: Mapped[int] = mapped_column(Integer, default=1)

    __table_args__ = (UniqueConstraint("job_id", "speaker", "version", name="uq_voice_assignment"),)


class Budget(Base, TimestampMixin):
    """예산. 잔액은 한도 - 누적 사용액 - 예약 합계입니다."""

    __tablename__ = "budgets"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    scope: Mapped[str] = mapped_column(String(32))
    scope_ref: Mapped[str | None] = mapped_column(String(64), default=None)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    limit_amount: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    spent_amount: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=Decimal("0"))

    __table_args__ = (
        UniqueConstraint("scope", "scope_ref", "period_start", name="uq_budget_scope_period"),
        CheckConstraint("scope in ('monthly','job')", name="ck_budget_scope"),
    )


class BudgetReservation(Base, TimestampMixin):
    """예약. 호출 전에 잡고 완료 후 정산합니다."""

    __tablename__ = "budget_reservations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    budget_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("budgets.id", ondelete="CASCADE"), index=True
    )
    stage_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("stage_runs.id"), default=None
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    state: Mapped[ReservationState] = mapped_column(
        state_column(ReservationState, 16), default=ReservationState.HELD
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    settled_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), default=None)

    __table_args__ = (Index("ix_budget_reservations_open", "budget_id", "state"),)


class Artifact(Base, TimestampMixin):
    """결과물. 대본·음성이 바뀌면 새 버전을 만들고 과거 승인과 분리합니다."""

    __tablename__ = "artifacts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("jobs.id"), index=True, default=None
    )
    clip_edit_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("clip_edits.id"), index=True, default=None
    )
    kind: Mapped[str] = mapped_column(String(32))
    version: Mapped[int] = mapped_column(Integer, default=1)
    storage_key: Mapped[str] = mapped_column(String(1024))
    checksum: Mapped[str | None] = mapped_column(String(128), default=None)
    render_settings: Mapped[dict] = mapped_column(JSON, default=dict)

    __table_args__ = (
        CheckConstraint(
            "(job_id is not null) or (clip_edit_id is not null)", name="ck_artifact_owner"
        ),
    )


class Approval(Base, TimestampMixin):
    """승인. 승인 대상은 결과물 버전이며 과거 승인을 재사용하지 않습니다."""

    __tablename__ = "approvals"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    artifact_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("artifacts.id"), index=True)
    approver_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    metadata_version: Mapped[int] = mapped_column(Integer, default=1)

    __table_args__ = (
        UniqueConstraint("artifact_id", "metadata_version", name="uq_approval_artifact_metadata"),
    )


class Publication(Base, TimestampMixin):
    """게시. 승인 버전·채널 조합에 유일성 제약을 둡니다."""

    __tablename__ = "publications"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    approval_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("approvals.id"), index=True)
    channel_id: Mapped[str] = mapped_column(String(64))
    upload_session_url: Mapped[str | None] = mapped_column(Text, default=None)
    youtube_video_id: Mapped[str | None] = mapped_column(String(32), default=None)
    scheduled_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    state: Mapped[PublicationState] = mapped_column(
        state_column(PublicationState, 32), default=PublicationState.PENDING
    )
    metadata_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    checkpoint: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    lease_token: Mapped[str | None] = mapped_column(String(36), default=None)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    replaces_publication_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("publications.id"), default=None
    )

    __table_args__ = (
        UniqueConstraint("approval_id", "channel_id", name="uq_publication_approval_channel"),
    )


class ClipCandidate(Base, TimestampMixin):
    """하이라이트 후보. 추천 결과는 데이터이며 실행 명령으로 쓰지 않습니다."""

    __tablename__ = "clip_candidates"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    source_asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source_assets.id", ondelete="CASCADE"), index=True
    )
    transcript_version: Mapped[int] = mapped_column(Integer, default=1)
    start_seconds: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    end_seconds: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    suggested_title: Mapped[str | None] = mapped_column(String(255), default=None)
    reason: Mapped[str | None] = mapped_column(Text, default=None)
    provider: Mapped[str | None] = mapped_column(String(64), default=None)
    model_id: Mapped[str | None] = mapped_column(String(128), default=None)
    selected: Mapped[bool] = mapped_column(Boolean, default=False)

    __table_args__ = (
        CheckConstraint("end_seconds > start_seconds", name="ck_clip_candidate_range"),
    )


class ClipEdit(Base, TimestampMixin):
    """숏폼 편집본. 원본을 덮어쓰지 않는 편집 결정만 담습니다."""

    __tablename__ = "clip_edits"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    source_asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source_assets.id", ondelete="CASCADE"), index=True
    )
    edit_version: Mapped[int] = mapped_column(Integer, default=1)
    output_language: Mapped[str] = mapped_column(String(16))
    use_original_audio: Mapped[bool] = mapped_column(Boolean, default=True)
    output_width: Mapped[int] = mapped_column(Integer, default=1080)
    output_height: Mapped[int] = mapped_column(Integer, default=1920)
    subtitle_style: Mapped[dict] = mapped_column(JSON, default=dict)
    screen_title: Mapped[str | None] = mapped_column(String(255), default=None)
    publish_title: Mapped[str | None] = mapped_column(String(255), default=None)
    created_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))

    ranges: Mapped[list[ClipRange]] = relationship(
        back_populates="clip_edit", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("source_asset_id", "edit_version", name="uq_clip_edit_version"),
    )


class ClipRange(Base, TimestampMixin):
    """숏폼 구간. 최초 버전은 편집본당 구간 하나로 제한합니다."""

    __tablename__ = "clip_ranges"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    clip_edit_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("clip_edits.id", ondelete="CASCADE"), index=True
    )
    source_start_seconds: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    source_end_seconds: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    output_order: Mapped[int] = mapped_column(Integer, default=0)
    crop: Mapped[dict] = mapped_column(JSON, default=dict)

    clip_edit: Mapped[ClipEdit] = relationship(back_populates="ranges")

    __table_args__ = (
        UniqueConstraint("clip_edit_id", "output_order", name="uq_clip_range_order"),
        CheckConstraint("source_end_seconds > source_start_seconds", name="ck_clip_range_positive"),
    )


class OutboxMessage(Base, TimestampMixin):
    """트랜잭션 outbox.

    DB에 실행 요청을 기록하는 트랜잭션과 같은 트랜잭션에서 이 행을 만들고,
    디스패처가 큐로 보냅니다. 큐 전송에 실패해도 요청이 사라지지 않습니다.
    """

    __tablename__ = "outbox_messages"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    topic: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)
    dedupe_key: Mapped[str] = mapped_column(String(255), unique=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, default=None)

    __table_args__ = (Index("ix_outbox_unpublished", "published_at", "created_at"),)


class MediaTask(Base, TimestampMixin):
    """Durable local analysis/render request; settings snapshot cannot be edited."""

    __tablename__ = "media_tasks"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    source_asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("source_assets.id"), index=True)
    clip_edit_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("clip_edits.id"), default=None
    )
    kind: Mapped[str] = mapped_column(String(32))
    state: Mapped[str] = mapped_column(String(16), default="pending")
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    __table_args__ = (
        CheckConstraint(
            "state in ('pending','running','succeeded','failed')", name="ck_media_task_state"
        ),
        CheckConstraint("kind in ('render','transcribe','scenes')", name="ck_media_task_kind"),
    )
