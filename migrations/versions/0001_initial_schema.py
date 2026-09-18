"""초기 스키마. docs/ARCHITECTURE.md와 docs/SHORT_FORM_EDITING.md의 엔터티.

Revision ID: 5411d18bd26b
Revises:
Create Date: 2026-09-18 09:16:58.747458
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "budgets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("scope_ref", sa.String(length=64), nullable=True),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("limit_amount", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("spent_amount", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("scope in ('monthly','job')", name="ck_budget_scope"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scope", "scope_ref", "period_start", name="uq_budget_scope_period"),
    )
    op.create_table(
        "glossaries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("source_language", sa.String(length=16), nullable=False),
        sa.Column("target_language", sa.String(length=16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("entries", sa.JSON(), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "outbox_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("topic", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("dedupe_key", sa.String(length=255), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedupe_key"),
    )
    with op.batch_alter_table("outbox_messages", schema=None) as batch_op:
        batch_op.create_index("ix_outbox_unpublished", ["published_at", "created_at"], unique=False)

    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_users_email"), ["email"], unique=True)

    op.create_table(
        "source_assets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("storage_key", sa.String(length=1024), nullable=False),
        sa.Column("original_filename", sa.String(length=512), nullable=False),
        sa.Column("checksum", sa.String(length=128), nullable=True),
        sa.Column("byte_size", sa.Integer(), nullable=True),
        sa.Column("duration_seconds", sa.Numeric(precision=12, scale=3), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("source_language", sa.String(length=16), nullable=True),
        sa.Column("upload_state", sa.String(length=32), nullable=False),
        sa.Column("probe_error", sa.Text(), nullable=True),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "upload_state in ('awaiting_upload','uploaded','verified','rejected')",
            name="ck_source_assets_upload_state",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("storage_key"),
    )
    op.create_table(
        "clip_candidates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_asset_id", sa.Uuid(), nullable=False),
        sa.Column("transcript_version", sa.Integer(), nullable=False),
        sa.Column("start_seconds", sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column("end_seconds", sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column("suggested_title", sa.String(length=255), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("provider", sa.String(length=64), nullable=True),
        sa.Column("model_id", sa.String(length=128), nullable=True),
        sa.Column("selected", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("end_seconds > start_seconds", name="ck_clip_candidate_range"),
        sa.ForeignKeyConstraint(["source_asset_id"], ["source_assets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("clip_candidates", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_clip_candidates_source_asset_id"), ["source_asset_id"], unique=False
        )

    op.create_table(
        "clip_edits",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_asset_id", sa.Uuid(), nullable=False),
        sa.Column("edit_version", sa.Integer(), nullable=False),
        sa.Column("output_language", sa.String(length=16), nullable=False),
        sa.Column("use_original_audio", sa.Boolean(), nullable=False),
        sa.Column("output_width", sa.Integer(), nullable=False),
        sa.Column("output_height", sa.Integer(), nullable=False),
        sa.Column("subtitle_style", sa.JSON(), nullable=False),
        sa.Column("screen_title", sa.String(length=255), nullable=True),
        sa.Column("publish_title", sa.String(length=255), nullable=True),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(["source_asset_id"], ["source_assets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_asset_id", "edit_version", name="uq_clip_edit_version"),
    )
    with op.batch_alter_table("clip_edits", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_clip_edits_source_asset_id"), ["source_asset_id"], unique=False
        )

    op.create_table(
        "jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_asset_id", sa.Uuid(), nullable=False),
        sa.Column("target_language", sa.String(length=16), nullable=False),
        sa.Column("settings_version", sa.Integer(), nullable=False),
        sa.Column("current_stage", sa.String(length=64), nullable=True),
        sa.Column(
            "state",
            sa.Enum(
                "queued",
                "processing",
                "blocked",
                "review_required",
                "approved",
                "rejected",
                "failed",
                "cancelled",
                name="jobstate",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("state_reason", sa.Text(), nullable=True),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["source_asset_id"],
            ["source_assets.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_jobs_source_asset_id"), ["source_asset_id"], unique=False
        )

    op.create_table(
        "artifacts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("clip_edit_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("storage_key", sa.String(length=1024), nullable=False),
        sa.Column("checksum", sa.String(length=128), nullable=True),
        sa.Column("render_settings", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(job_id is not null) or (clip_edit_id is not null)", name="ck_artifact_owner"
        ),
        sa.ForeignKeyConstraint(
            ["clip_edit_id"],
            ["clip_edits.id"],
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["jobs.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("artifacts", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_artifacts_clip_edit_id"), ["clip_edit_id"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_artifacts_job_id"), ["job_id"], unique=False)

    op.create_table(
        "clip_ranges",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("clip_edit_id", sa.Uuid(), nullable=False),
        sa.Column("source_start_seconds", sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column("source_end_seconds", sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column("output_order", sa.Integer(), nullable=False),
        sa.Column("crop", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "source_end_seconds > source_start_seconds", name="ck_clip_range_positive"
        ),
        sa.ForeignKeyConstraint(["clip_edit_id"], ["clip_edits.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("clip_edit_id", "output_order", name="uq_clip_range_order"),
    )
    with op.batch_alter_table("clip_ranges", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_clip_ranges_clip_edit_id"), ["clip_edit_id"], unique=False
        )

    op.create_table(
        "stage_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("source_asset_id", sa.Uuid(), nullable=True),
        sa.Column("stage", sa.String(length=64), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("reusable", sa.Boolean(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column(
            "state",
            sa.Enum(
                "pending",
                "running",
                "succeeded",
                "failed",
                "cancelled",
                name="stagerunstate",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("provider", sa.String(length=64), nullable=True),
        sa.Column("provider_job_id", sa.String(length=255), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("estimated_cost", sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column("actual_cost", sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_asset_id"], ["source_assets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "job_id", "stage", "input_hash", "attempt", name="uq_stage_run_attempt"
        ),
    )
    with op.batch_alter_table("stage_runs", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_stage_runs_input_hash"), ["input_hash"], unique=False)
        batch_op.create_index(batch_op.f("ix_stage_runs_job_id"), ["job_id"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_stage_runs_source_asset_id"), ["source_asset_id"], unique=False
        )

    op.create_table(
        "voice_assignments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("speaker", sa.String(length=64), nullable=False),
        sa.Column("provider_voice_id", sa.String(length=128), nullable=False),
        sa.Column("settings", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "speaker", "version", name="uq_voice_assignment"),
    )
    with op.batch_alter_table("voice_assignments", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_voice_assignments_job_id"), ["job_id"], unique=False)

    op.create_table(
        "approvals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("artifact_id", sa.Uuid(), nullable=False),
        sa.Column("approver_id", sa.Uuid(), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["approver_id"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["artifact_id"],
            ["artifacts.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "artifact_id", "metadata_version", name="uq_approval_artifact_metadata"
        ),
    )
    with op.batch_alter_table("approvals", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_approvals_artifact_id"), ["artifact_id"], unique=False)

    op.create_table(
        "budget_reservations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("budget_id", sa.Uuid(), nullable=False),
        sa.Column("stage_run_id", sa.Uuid(), nullable=True),
        sa.Column("amount", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column(
            "state",
            sa.Enum(
                "held",
                "settled",
                "released",
                "expired",
                name="reservationstate",
                native_enum=False,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("settled_amount", sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["budget_id"], ["budgets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["stage_run_id"],
            ["stage_runs.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("budget_reservations", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_budget_reservations_budget_id"), ["budget_id"], unique=False
        )
        batch_op.create_index("ix_budget_reservations_open", ["budget_id", "state"], unique=False)

    op.create_table(
        "transcript_segments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_asset_id", sa.Uuid(), nullable=False),
        sa.Column("stage_run_id", sa.Uuid(), nullable=True),
        sa.Column("speaker", sa.String(length=64), nullable=True),
        sa.Column("start_seconds", sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column("end_seconds", sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("transcript_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("end_seconds >= start_seconds", name="ck_transcript_segment_range"),
        sa.ForeignKeyConstraint(["source_asset_id"], ["source_assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["stage_run_id"],
            ["stage_runs.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("transcript_segments", schema=None) as batch_op:
        batch_op.create_index(
            "ix_transcript_segments_asset_start", ["source_asset_id", "start_seconds"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_transcript_segments_source_asset_id"), ["source_asset_id"], unique=False
        )

    op.create_table(
        "publications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("approval_id", sa.Uuid(), nullable=False),
        sa.Column("channel_id", sa.String(length=64), nullable=False),
        sa.Column("upload_session_url", sa.Text(), nullable=True),
        sa.Column("youtube_video_id", sa.String(length=32), nullable=True),
        sa.Column("scheduled_at_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "state",
            sa.Enum(
                "pending",
                "uploading",
                "processing_on_youtube",
                "scheduled",
                "published",
                "superseded",
                "failed",
                "cancelled",
                name="publicationstate",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("replaces_publication_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["approval_id"],
            ["approvals.id"],
        ),
        sa.ForeignKeyConstraint(
            ["replaces_publication_id"],
            ["publications.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("approval_id", "channel_id", name="uq_publication_approval_channel"),
    )
    with op.batch_alter_table("publications", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_publications_approval_id"), ["approval_id"], unique=False
        )

    op.create_table(
        "translated_segments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("transcript_segment_id", sa.Uuid(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("edit_version", sa.Integer(), nullable=False),
        sa.Column("voice_key", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["transcript_segment_id"], ["transcript_segments.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("translated_segments", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_translated_segments_job_id"), ["job_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("translated_segments", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_translated_segments_job_id"))

    op.drop_table("translated_segments")
    with op.batch_alter_table("publications", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_publications_approval_id"))

    op.drop_table("publications")
    with op.batch_alter_table("transcript_segments", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_transcript_segments_source_asset_id"))
        batch_op.drop_index("ix_transcript_segments_asset_start")

    op.drop_table("transcript_segments")
    with op.batch_alter_table("budget_reservations", schema=None) as batch_op:
        batch_op.drop_index("ix_budget_reservations_open")
        batch_op.drop_index(batch_op.f("ix_budget_reservations_budget_id"))

    op.drop_table("budget_reservations")
    with op.batch_alter_table("approvals", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_approvals_artifact_id"))

    op.drop_table("approvals")
    with op.batch_alter_table("voice_assignments", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_voice_assignments_job_id"))

    op.drop_table("voice_assignments")
    with op.batch_alter_table("stage_runs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_stage_runs_source_asset_id"))
        batch_op.drop_index(batch_op.f("ix_stage_runs_job_id"))
        batch_op.drop_index(batch_op.f("ix_stage_runs_input_hash"))

    op.drop_table("stage_runs")
    with op.batch_alter_table("clip_ranges", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_clip_ranges_clip_edit_id"))

    op.drop_table("clip_ranges")
    with op.batch_alter_table("artifacts", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_artifacts_job_id"))
        batch_op.drop_index(batch_op.f("ix_artifacts_clip_edit_id"))

    op.drop_table("artifacts")
    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_jobs_source_asset_id"))

    op.drop_table("jobs")
    with op.batch_alter_table("clip_edits", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_clip_edits_source_asset_id"))

    op.drop_table("clip_edits")
    with op.batch_alter_table("clip_candidates", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_clip_candidates_source_asset_id"))

    op.drop_table("clip_candidates")
    op.drop_table("source_assets")
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_users_email"))

    op.drop_table("users")
    with op.batch_alter_table("outbox_messages", schema=None) as batch_op:
        batch_op.drop_index("ix_outbox_unpublished")

    op.drop_table("outbox_messages")
    op.drop_table("glossaries")
    op.drop_table("budgets")
