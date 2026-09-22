"""대본 세그먼트에 겹침 표시(overlap) 열 추가.

두 사람이 동시에 말한 시간에 걸친 자막을 표시합니다. NULL은 "아직 안 재 봤다"라서
기존 행과 화자 분리를 돌리지 않은 대본은 "겹치지 않음"으로 잘못 읽히지 않습니다.
0010_silence_preview 뒤에 붙입니다.
"""

import sqlalchemy as sa
from alembic import op

revision = "0011_transcript_overlap"
down_revision = "0010_silence_preview"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("transcript_segments", schema=None) as batch:
        batch.add_column(sa.Column("overlap", sa.Boolean(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("transcript_segments", schema=None) as batch:
        batch.drop_column("overlap")
