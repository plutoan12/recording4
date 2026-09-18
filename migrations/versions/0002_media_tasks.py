"""Durable media analysis/render tasks."""

import sqlalchemy as sa
from alembic import op

revision = "0002_media_tasks"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "media_tasks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("source_asset_id", sa.Uuid(), sa.ForeignKey("source_assets.id"), nullable=False),
        sa.Column("clip_edit_id", sa.Uuid(), sa.ForeignKey("clip_edits.id")),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("settings", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "state in ('pending','running','succeeded','failed')", name="ck_media_task_state"
        ),
        sa.CheckConstraint("kind in ('render','transcribe','scenes')", name="ck_media_task_kind"),
    )
    op.create_index("ix_media_tasks_source_asset_id", "media_tasks", ["source_asset_id"])


def downgrade():
    op.drop_table("media_tasks")
