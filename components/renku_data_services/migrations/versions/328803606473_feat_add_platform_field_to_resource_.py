"""feat: add platform field to resource pools.

Revision ID: 328803606473
Revises: df2c0e65612a
Create Date: 2025-11-17 12:50:15.907221

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "328803606473"
down_revision = "df2c0e65612a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "resource_pools",
        sa.Column("platform", sa.Enum("linux_amd64", "linux_arm64", name="build_platform"), nullable=True),
        schema="resource_pools",
    )


def downgrade() -> None:
    op.drop_column("resource_pools", "platform", schema="resource_pools")
