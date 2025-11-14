"""add platforms field to build_parameters

Revision ID: df2c0e65612a
Revises: d437be68a4fb
Create Date: 2025-11-03 08:59:27.001063

"""

import sqlalchemy as sa
from alembic import op

from renku_data_services.utils.sqlalchemy import ULIDType

# revision identifiers, used by Alembic.
revision = "df2c0e65612a"
down_revision = "d437be68a4fb"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "build_platforms",
        sa.Column("id", sa.Integer(), sa.Identity(always=True), nullable=False),
        sa.Column("platform", sa.Enum("linux_amd64", "linux_arm64", name="build_platform"), nullable=False),
        sa.Column("build_parameters_id", ULIDType(), nullable=False),
        sa.ForeignKeyConstraint(
            ["build_parameters_id"],
            ["sessions.build_parameters.id"],
            name="build_platform_build_parameters_id_fk",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="sessions",
    )


def downgrade() -> None:
    op.drop_table("build_platforms", schema="sessions")
    op.execute("DROP type build_platform")
