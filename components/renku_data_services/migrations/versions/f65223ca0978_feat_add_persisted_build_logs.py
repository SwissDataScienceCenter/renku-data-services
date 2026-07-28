"""feat: add persisted build logs

Revision ID: f65223ca0978
Revises: 906ec89ea06f
Create Date: 2026-07-28 07:59:44.706230

"""

import sqlalchemy as sa
from alembic import op

from renku_data_services.utils.sqlalchemy import ULIDType

# revision identifiers, used by Alembic.
revision = "f65223ca0978"
down_revision = "906ec89ea06f"
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


def downgrade() -> None:
    op.drop_index(
        op.f("ix_persisted_logs_image_build_logs_timestamp"), table_name="image_build_logs", schema="persisted_logs"
    )
    op.drop_index(
        op.f("ix_persisted_logs_image_build_logs_build_id"), table_name="image_build_logs", schema="persisted_logs"
    )
    op.drop_table("image_build_logs", schema="persisted_logs")
