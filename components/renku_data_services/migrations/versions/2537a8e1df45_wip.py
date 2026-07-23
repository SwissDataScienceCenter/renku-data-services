"""wip

Revision ID: 2537a8e1df45
Revises: eadfb5e7e7cb
Create Date: 2026-07-15 11:42:06.232593

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "2537a8e1df45"
down_revision = "eadfb5e7e7cb"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index(
        "ix_persisted_logs_amalthea_session_logs_run_id", table_name="amalthea_session_logs", schema="persisted_logs"
    )
    op.drop_table("amalthea_session_logs", schema="persisted_logs")
    op.drop_index("ix_persisted_logs_session_runs_launcher_id", table_name="session_runs", schema="persisted_logs")
    op.drop_index("ix_persisted_logs_session_runs_user_id", table_name="session_runs", schema="persisted_logs")
    op.drop_table("session_runs", schema="persisted_logs")


def downgrade() -> None:
    op.create_table(
        "session_runs",
        sa.Column("id", sa.VARCHAR(), autoincrement=False, nullable=False),
        sa.Column("user_id", sa.VARCHAR(length=36), autoincrement=False, nullable=False),
        sa.Column("launch_id", sa.VARCHAR(), autoincrement=False, nullable=False),
        sa.Column("launcher_id", sa.VARCHAR(), autoincrement=False, nullable=False),
        sa.Column("submission_id", sa.VARCHAR(), autoincrement=False, nullable=True),
        sa.Column("first_log", postgresql.TIMESTAMP(timezone=True), autoincrement=False, nullable=False),
        sa.Column("last_log", postgresql.TIMESTAMP(timezone=True), autoincrement=False, nullable=False),
        sa.ForeignKeyConstraint(["launcher_id"], ["sessions.launchers.id"], name="session_runs_launcher_id_fkey"),
        sa.ForeignKeyConstraint(["user_id"], ["users.users.keycloak_id"], name="session_runs_user_id_fkey"),
        sa.PrimaryKeyConstraint("id", name="session_runs_pkey"),
        schema="persisted_logs",
    )
    op.create_index(
        "ix_persisted_logs_session_runs_user_id", "session_runs", ["user_id"], unique=False, schema="persisted_logs"
    )
    op.create_index(
        "ix_persisted_logs_session_runs_launcher_id",
        "session_runs",
        ["launcher_id"],
        unique=False,
        schema="persisted_logs",
    )
    op.create_table(
        "amalthea_session_logs",
        sa.Column("id", sa.VARCHAR(), server_default=sa.text("generate_ulid()"), autoincrement=False, nullable=False),
        sa.Column("run_id", sa.VARCHAR(), autoincrement=False, nullable=False),
        sa.Column("container", sa.VARCHAR(), autoincrement=False, nullable=False),
        sa.Column("timestamp", postgresql.TIMESTAMP(timezone=True), autoincrement=False, nullable=False),
        sa.Column("log_line", sa.VARCHAR(), autoincrement=False, nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"], ["persisted_logs.session_runs.id"], name="amalthea_session_logs_run_id_fkey", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="amalthea_session_logs_pkey"),
        schema="persisted_logs",
    )
    op.create_index(
        "ix_persisted_logs_amalthea_session_logs_run_id",
        "amalthea_session_logs",
        ["run_id"],
        unique=False,
        schema="persisted_logs",
    )
