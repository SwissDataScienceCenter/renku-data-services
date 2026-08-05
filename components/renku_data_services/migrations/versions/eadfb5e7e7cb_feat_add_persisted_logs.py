"""feat: add persisted logs

Revision ID: eadfb5e7e7cb
Revises: 36435401b2e7
Create Date: 2026-07-13 12:35:55.042555

"""

import sqlalchemy as sa
from alembic import op

from renku_data_services.utils.sqlalchemy import ULIDType

# revision identifiers, used by Alembic.
revision = "eadfb5e7e7cb"
down_revision = "36435401b2e7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "image_build_logs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("build_id", ULIDType(), nullable=False),
        sa.Column("container", sa.String(), nullable=False),
        sa.Column("timestamp", sa.BigInteger(), nullable=False),
        sa.Column("log_line", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["build_id"], ["sessions.builds.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema="persisted_logs",
    )
    op.create_index(
        op.f("ix_persisted_logs_image_build_logs_build_id"),
        "image_build_logs",
        ["build_id"],
        unique=False,
        schema="persisted_logs",
    )
    op.create_index(
        op.f("ix_persisted_logs_image_build_logs_timestamp"),
        "image_build_logs",
        ["timestamp"],
        unique=False,
        schema="persisted_logs",
    )
    op.create_table(
        "session_runs",
        sa.Column("id", ULIDType(), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("session_uid", sa.String(), nullable=True),
        sa.Column("launcher_id", ULIDType(), nullable=False),
        sa.Column("submission_id", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(
            ["launcher_id"],
            ["sessions.launchers.id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.users.keycloak_id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="persisted_logs",
    )
    op.create_index(
        op.f("ix_persisted_logs_session_runs_launcher_id"),
        "session_runs",
        ["launcher_id"],
        unique=False,
        schema="persisted_logs",
    )
    op.create_index(
        op.f("ix_persisted_logs_session_runs_user_id"),
        "session_runs",
        ["user_id"],
        unique=False,
        schema="persisted_logs",
    )
    op.create_table(
        "amalthea_session_logs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("run_id", ULIDType(), nullable=False),
        sa.Column("container", sa.String(), nullable=False),
        sa.Column("timestamp", sa.BigInteger(), nullable=False),
        sa.Column("log_line", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["persisted_logs.session_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema="persisted_logs",
    )
    op.create_index(
        op.f("ix_persisted_logs_amalthea_session_logs_run_id"),
        "amalthea_session_logs",
        ["run_id"],
        unique=False,
        schema="persisted_logs",
    )
    op.create_index(
        op.f("ix_persisted_logs_amalthea_session_logs_timestamp"),
        "amalthea_session_logs",
        ["timestamp"],
        unique=False,
        schema="persisted_logs",
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_persisted_logs_amalthea_session_logs_timestamp"),
        table_name="amalthea_session_logs",
        schema="persisted_logs",
    )
    op.drop_index(
        op.f("ix_persisted_logs_amalthea_session_logs_run_id"),
        table_name="amalthea_session_logs",
        schema="persisted_logs",
    )
    op.drop_table("amalthea_session_logs", schema="persisted_logs")
    op.drop_index(op.f("ix_persisted_logs_session_runs_user_id"), table_name="session_runs", schema="persisted_logs")
    op.drop_index(
        op.f("ix_persisted_logs_session_runs_launcher_id"), table_name="session_runs", schema="persisted_logs"
    )
    op.drop_table("session_runs", schema="persisted_logs")
    op.drop_index(
        op.f("ix_persisted_logs_image_build_logs_timestamp"), table_name="image_build_logs", schema="persisted_logs"
    )
    op.drop_index(
        op.f("ix_persisted_logs_image_build_logs_build_id"), table_name="image_build_logs", schema="persisted_logs"
    )
    op.drop_table("image_build_logs", schema="persisted_logs")
