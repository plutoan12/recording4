"""얼굴 제안(faces)과 하이라이트 추천(highlights) 작업 종류 추가.

faces는 앞선 변경에서 API가 받도록 해 놓고 **제약에 넣지 않았습니다.** 요청하면
DB가 거절했습니다(실측: CHECK constraint failed: ck_media_task_kind). 시험이 그
종류로 행을 넣어 본 적이 없어 드러나지 않았습니다.
"""

from alembic import op

revision = "0006_faces_highlights"
down_revision = "0005_diarize"
branch_labels = None
depends_on = None

KINDS_AFTER = "kind in ('render','transcribe','scenes','align','diarize','faces','highlights')"
KINDS_BEFORE = "kind in ('render','transcribe','scenes','align','diarize')"


def _replace(condition: str) -> None:
    # batch 모드는 SQLite에서 테이블을 다시 만들고 PostgreSQL에서는 직접 실행합니다.
    with op.batch_alter_table("media_tasks") as batch:
        batch.drop_constraint("ck_media_task_kind", type_="check")
        batch.create_check_constraint("ck_media_task_kind", condition)


def upgrade() -> None:
    _replace(KINDS_AFTER)


def downgrade() -> None:
    # 제약을 되돌리기 전에 새 종류의 행을 먼저 지웁니다.
    op.execute("DELETE FROM media_tasks WHERE kind in ('faces','highlights')")
    _replace(KINDS_BEFORE)
