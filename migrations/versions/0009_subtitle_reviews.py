"""GitHub 저장소 자막 검수(subtitle_reviews) 표 추가.

작업 하나와 검수 브랜치·PR 하나를 잇습니다. 가져온 번역은 이 표에만 두고 작업에
자동으로 넣지 않습니다. 0008_translation_memory 뒤에 붙입니다.
"""

import sqlalchemy as sa
from alembic import op

revision = "0009_subtitle_reviews"
down_revision = "0008_translation_memory"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "subtitle_reviews",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("language", sa.String(length=16), nullable=False),
        sa.Column("branch", sa.String(length=255), nullable=False),
        sa.Column("path", sa.String(length=512), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("pull_number", sa.Integer(), nullable=True),
        sa.Column("pull_url", sa.String(length=512), nullable=True),
        sa.Column("commit_sha", sa.String(length=64), nullable=True),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("kind in ('export','import')", name="ck_subtitle_review_kind"),
        sa.CheckConstraint(
            "state in ('pending','running','succeeded','failed')", name="ck_subtitle_review_state"
        ),
    )
    with op.batch_alter_table("subtitle_reviews", schema=None) as batch:
        batch.create_index(batch.f("ix_subtitle_reviews_job_id"), ["job_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("subtitle_reviews", schema=None) as batch:
        batch.drop_index(batch.f("ix_subtitle_reviews_job_id"))
    op.drop_table("subtitle_reviews")
