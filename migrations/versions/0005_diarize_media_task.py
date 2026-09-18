"""화자 분리(diarize) 작업 종류 추가."""

from alembic import op

revision = "0005_diarize"
down_revision = "0004_align"
branch_labels = None
depends_on = None

KINDS_WITH_DIARIZE = "kind in ('render','transcribe','scenes','align','diarize')"
KINDS_BEFORE = "kind in ('render','transcribe','scenes','align')"


def _replace(condition: str) -> None:
    # batch 모드는 SQLite에서 테이블을 다시 만들고 PostgreSQL에서는 직접 실행합니다.
    with op.batch_alter_table("media_tasks") as batch:
        batch.drop_constraint("ck_media_task_kind", type_="check")
        batch.create_check_constraint("ck_media_task_kind", condition)


def upgrade() -> None:
    _replace(KINDS_WITH_DIARIZE)


def downgrade() -> None:
    # 제약을 되돌리기 전에 새 종류의 행을 먼저 지웁니다.
    op.execute("DELETE FROM media_tasks WHERE kind = 'diarize'")
    _replace(KINDS_BEFORE)
