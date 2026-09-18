"""타이밍 없는 대본 정렬(align) 작업 종류 추가."""

from alembic import op

revision = "0004_align"
down_revision = "0003_workflow"
branch_labels = None
depends_on = None

KINDS_WITH_ALIGN = "kind in ('render','transcribe','scenes','align')"
KINDS_BEFORE = "kind in ('render','transcribe','scenes')"


def _replace(condition: str) -> None:
    # batch 모드는 SQLite에서 테이블을 다시 만들고 PostgreSQL에서는 직접 실행합니다.
    with op.batch_alter_table("media_tasks") as batch:
        batch.drop_constraint("ck_media_task_kind", type_="check")
        batch.create_check_constraint("ck_media_task_kind", condition)


def upgrade() -> None:
    _replace(KINDS_WITH_ALIGN)


def downgrade() -> None:
    op.execute("DELETE FROM media_tasks WHERE kind = 'align'")
    _replace(KINDS_BEFORE)
