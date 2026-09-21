"""번역 기억(translation_memory) 표 추가.

같은 문장을 같은 방향으로 다시 번역하지 않기 위한 캐시입니다. 키는 출발·목표
언어와 원문·용어집 버전·공급자의 해시입니다. 0007_faces_highlights 뒤에 붙습니다.
"""

import sqlalchemy as sa
from alembic import op

revision = "0008_translation_memory"
down_revision = "0007_faces_highlights"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "translation_memory",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_language", sa.String(length=16), nullable=False),
        sa.Column("target_language", sa.String(length=16), nullable=False),
        sa.Column("text_hash", sa.String(length=64), nullable=False),
        sa.Column("source_text", sa.Text(), nullable=False),
        sa.Column("translated_text", sa.Text(), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("glossary_version", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_language", "target_language", "text_hash", name="uq_translation_memory"
        ),
    )


def downgrade() -> None:
    op.drop_table("translation_memory")
