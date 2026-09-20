"""대본 구간에 단어 시각(words) 추가. 노래방·단어별 자막 움직임이 씁니다."""

import sqlalchemy as sa
from alembic import op

revision = "0007_transcript_words"
down_revision = "0006_sync"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("transcript_segments") as batch:
        batch.add_column(sa.Column("words", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("transcript_segments") as batch:
        batch.drop_column("words")
