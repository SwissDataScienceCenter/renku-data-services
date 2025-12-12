"""add hibernation_warning_period

Revision ID: 9b18adb58e63
Revises: 5ec28ea89e0a
Create Date: 2025-12-12 09:17:45.339562

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "9b18adb58e63"
down_revision = "5ec28ea89e0a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "resource_pools", sa.Column("hibernation_warning_period", sa.Integer(), nullable=True), schema="resource_pools"
    )


def downgrade() -> None:
    op.drop_column("resource_pools", "hibernation_warning_period", schema="resource_pools")
