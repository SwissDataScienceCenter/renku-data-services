"""wip: update persisted logs

Revision ID: 906ec89ea06f
Revises: 01180f797019
Create Date: 2026-07-22 08:50:21.380775

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "906ec89ea06f"
down_revision = "01180f797019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DELETE FROM persisted_logs.session_runs")
    op.add_column("session_runs", sa.Column("session_uid", sa.String(), nullable=True), schema="persisted_logs")
    op.drop_column("session_runs", "launch_id", schema="persisted_logs")


def downgrade() -> None:
    op.add_column(
        "session_runs",
        sa.Column("launch_id", sa.VARCHAR(), autoincrement=False, nullable=False),
        schema="persisted_logs",
    )
    op.drop_column("session_runs", "session_uid", schema="persisted_logs")
