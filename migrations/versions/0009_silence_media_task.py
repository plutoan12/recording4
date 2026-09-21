"""무음 컷 미리 재기(silence) 작업 종류 추가."""

from alembic import op

revision = "0009_silence"
down_revision = "0008_highlights"
branch_labels = None
depends_on = None

KINDS_WITH_SILENCE = (
    "kind in ('render','transcribe','scenes','align','diarize','sync','highlights','silence')"
)
KINDS_BEFORE = "kind in ('render','transcribe','scenes','align','diarize','sync','highlights')"


def _replace(condition: str) -> None:
    # batch 모드는 SQLite에서 테이블을 다시 만들고 PostgreSQL에서는 직접 실행합니다.
    with op.batch_alter_table("media_tasks") as batch:
        batch.drop_constraint("ck_media_task_kind", type_="check")
        batch.create_check_constraint("ck_media_task_kind", condition)


def upgrade() -> None:
    _replace(KINDS_WITH_SILENCE)


def downgrade() -> None:
    # 제약을 되돌리기 전에 새 종류의 행을 먼저 지웁니다.
    op.execute("DELETE FROM media_tasks WHERE kind = 'silence'")
    _replace(KINDS_BEFORE)
