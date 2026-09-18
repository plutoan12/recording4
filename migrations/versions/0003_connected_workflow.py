"""Persist workflow snapshots, provider results and publication checkpoints."""

import sqlalchemy as sa
from alembic import op

revision = "0003_workflow"
down_revision = "0002_media_tasks"
branch_labels = None
depends_on = None


def upgrade():
    for table, columns in {
        "jobs": ["workflow_config", "workflow_data"],
        "stage_runs": ["outputs"],
        "publications": ["metadata_snapshot", "checkpoint"],
    }.items():
        for name in columns:
            op.add_column(table, sa.Column(name, sa.JSON(), nullable=False, server_default="{}"))
    for table in ("jobs", "publications"):
        op.add_column(table, sa.Column("lease_token", sa.String(36)))
        op.add_column(table, sa.Column("lease_until", sa.DateTime(timezone=True)))
    op.add_column("publications", sa.Column("error", sa.Text()))
    op.add_column(
        "outbox_messages", sa.Column("available_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.execute("UPDATE outbox_messages SET available_at = created_at")


def downgrade():
    op.drop_column("outbox_messages", "available_at")
    op.drop_column("publications", "error")
    for table in ("jobs", "publications"):
        op.drop_column(table, "lease_until")
        op.drop_column(table, "lease_token")
    for table, columns in {
        "jobs": ["workflow_config", "workflow_data"],
        "stage_runs": ["outputs"],
        "publications": ["metadata_snapshot", "checkpoint"],
    }.items():
        for name in columns:
            op.drop_column(table, name)
