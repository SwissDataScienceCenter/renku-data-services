"""feat: add session runners

Revision ID: c626b83fb3d4
Revises: 21c885ddf188
Create Date: 2026-09-09 11:10:08.591340

"""

import sqlalchemy as sa
from alembic import op

from renku_data_services.utils.sqlalchemy import ULIDType

# revision identifiers, used by Alembic.
revision = "c626b83fb3d4"
down_revision = "21c885ddf188"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "runners",
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
        schema="session_runners",
    )
    op.create_index(
        op.f("ix_session_runners_runners_registration_token"),
        "runners",
        ["registration_token"],
        unique=False,
        schema="session_runners",
    )
    op.create_index(
        op.f("ix_session_runners_runners_resource_pool_id"),
        "runners",
        ["resource_pool_id"],
        unique=False,
        schema="session_runners",
    )
    op.create_index(
        op.f("ix_session_runners_runners_user_id"), "runners", ["user_id"], unique=False, schema="session_runners"
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_session_runners_runners_user_id"), table_name="runners", schema="session_runners")
    op.drop_index(op.f("ix_session_runners_runners_resource_pool_id"), table_name="runners", schema="session_runners")
    op.drop_index(op.f("ix_session_runners_runners_registration_token"), table_name="runners", schema="session_runners")
    op.drop_table("runners", schema="session_runners")
    op.execute("DROP TYPE runnerstatus CASCADE")
