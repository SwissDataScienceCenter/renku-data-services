"""add hibernation_warning_period

Revision ID: 9b18adb58e63
Revises: 5ec28ea89e0a
Create Date: 2025-12-12 09:17:45.339562

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "9b18adb58e63"
down_revision = "4cbb36ac2a5c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "resource_pools", sa.Column("hibernation_warning_period", sa.Integer(), nullable=True), schema="resource_pools"
    )
    op.execute("""
    update "resource_pools"."resource_pools"
    set hibernation_warning_period = case
      when hibernation_threshold > 900 then 900
      else (hibernation_threshold * 0.5)::integer
    end
    where resource_pools.hibernation_threshold is not null""")


def downgrade() -> None:
    op.drop_column("resource_pools", "hibernation_warning_period", schema="resource_pools")
