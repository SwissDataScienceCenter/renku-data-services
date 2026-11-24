"""feat: add user-scoped session runners

Revision ID: c626b83fb3d4
Revises: 3016b9c4de5e
Create Date: 2026-09-09 11:10:08.591340

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from renku_data_services.utils.sqlalchemy import ULIDType

# revision identifiers, used by Alembic.
revision = "c626b83fb3d4"
down_revision = "3016b9c4de5e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_runners",
        sa.Column("id", ULIDType(), server_default=sa.text("generate_ulid()"), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("resource_pool_id", sa.Integer(), nullable=False),
        sa.Column("creation_date", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("registration_token", sa.String(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("never_contacted", "initializing", "ready", "not_ready", name="runnerstatus"),
            server_default="never_contacted",
            nullable=False,
        ),
        sa.Column("last_contact", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["resource_pool_id"], ["resource_pools.resource_pools.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.users.keycloak_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("registration_token"),
        schema="session_runners",
    )
    op.create_index(
        op.f("ix_session_runners_user_runners_resource_pool_id"),
        "user_runners",
        ["resource_pool_id"],
        unique=False,
        schema="session_runners",
    )
    op.create_index(
        op.f("ix_session_runners_user_runners_user_id"),
        "user_runners",
        ["user_id"],
        unique=False,
        schema="session_runners",
    )
    op.create_table(
        "remote_user_sessions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("resource_pool_id", sa.Integer(), nullable=False),
        sa.Column("runner_id", ULIDType(), nullable=True),
        sa.Column(
            "secrets",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            server_default=sa.text("NULL"),
            nullable=True,
        ),
        sa.Column("creation_date", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["resource_pool_id"], ["resource_pools.resource_pools.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["runner_id"], ["session_runners.user_runners.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.users.keycloak_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema="session_runners",
    )
    op.create_index(
        op.f("ix_session_runners_remote_user_sessions_resource_pool_id"),
        "remote_user_sessions",
        ["resource_pool_id"],
        unique=False,
        schema="session_runners",
    )
    op.create_index(
        op.f("ix_session_runners_remote_user_sessions_runner_id"),
        "remote_user_sessions",
        ["runner_id"],
        unique=False,
        schema="session_runners",
    )
    op.create_index(
        op.f("ix_session_runners_remote_user_sessions_user_id"),
        "remote_user_sessions",
        ["user_id"],
        unique=False,
        schema="session_runners",
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_session_runners_remote_user_sessions_user_id"),
        table_name="remote_user_sessions",
        schema="session_runners",
    )
    op.drop_index(
        op.f("ix_session_runners_remote_user_sessions_runner_id"),
        table_name="remote_user_sessions",
        schema="session_runners",
    )
    op.drop_index(
        op.f("ix_session_runners_remote_user_sessions_resource_pool_id"),
        table_name="remote_user_sessions",
        schema="session_runners",
    )
    op.drop_table("remote_user_sessions", schema="session_runners")
    op.drop_index(op.f("ix_session_runners_user_runners_user_id"), table_name="user_runners", schema="session_runners")
    op.drop_index(
        op.f("ix_session_runners_user_runners_resource_pool_id"), table_name="user_runners", schema="session_runners"
    )
    op.drop_table("user_runners", schema="session_runners")
    op.execute("DROP TYPE runnerstatus CASCADE")
