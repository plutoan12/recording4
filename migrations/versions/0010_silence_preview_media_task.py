"""무음 구간 제안(silence)과 편집 미리보기 한 장(preview) 작업 종류 추가.

0009_subtitle_reviews 뒤에 붙입니다. 같은 자리에 두 개를 두면 머리가 둘이 되어
`alembic upgrade head`가 멈춥니다.
"""

from alembic import op

revision = "0010_silence_preview"
down_revision = "0009_subtitle_reviews"
branch_labels = None
depends_on = None

KINDS_AFTER = (
    "kind in ('render','transcribe','scenes','align','diarize','sync',"
    "'faces','highlights','silence','preview')"
)
KINDS_BEFORE = (
    "kind in ('render','transcribe','scenes','align','diarize','sync','faces','highlights')"
)


def _replace(condition: str) -> None:
    with op.batch_alter_table("media_tasks") as batch:
        batch.drop_constraint("ck_media_task_kind", type_="check")
        batch.create_check_constraint("ck_media_task_kind", condition)


def upgrade() -> None:
    _replace(KINDS_AFTER)


def downgrade() -> None:
    # 제약을 되돌리기 전에 새 종류의 행을 먼저 지웁니다.
    op.execute("DELETE FROM media_tasks WHERE kind in ('silence','preview')")
    _replace(KINDS_BEFORE)
