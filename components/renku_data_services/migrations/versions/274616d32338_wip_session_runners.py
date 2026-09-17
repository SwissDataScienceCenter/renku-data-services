"""wip: session runners

Revision ID: 274616d32338
Revises: c626b83fb3d4
Create Date: 2026-09-16 07:55:51.408655

"""

import sqlalchemy as sa
from alembic import op

from renku_data_services.utils.sqlalchemy import ULIDType

# revision identifiers, used by Alembic.
revision = "274616d32338"
down_revision = "c626b83fb3d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "assigned_sessions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("resource_pool_id", sa.Integer(), nullable=False),
        sa.Column("runner_id", ULIDType(), nullable=True),
        sa.Column("creation_date", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["resource_pool_id"], ["resource_pools.resource_pools.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["runner_id"], ["session_runners.runners.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.users.keycloak_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema="session_runners",
    )
    op.create_index(
        op.f("ix_session_runners_assigned_sessions_resource_pool_id"),
        "assigned_sessions",
        ["resource_pool_id"],
        unique=False,
        schema="session_runners",
    )
    op.create_index(
        op.f("ix_session_runners_assigned_sessions_runner_id"),
        "assigned_sessions",
        ["runner_id"],
        unique=False,
        schema="session_runners",
    )
    op.create_index(
        op.f("ix_session_runners_assigned_sessions_user_id"),
        "assigned_sessions",
        ["user_id"],
        unique=False,
        schema="session_runners",
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_session_runners_assigned_sessions_user_id"), table_name="assigned_sessions", schema="session_runners"
    )
    op.drop_index(
        op.f("ix_session_runners_assigned_sessions_runner_id"), table_name="assigned_sessions", schema="session_runners"
    )
    op.drop_index(
        op.f("ix_session_runners_assigned_sessions_resource_pool_id"),
        table_name="assigned_sessions",
        schema="session_runners",
    )
    op.drop_table("assigned_sessions", schema="session_runners")
