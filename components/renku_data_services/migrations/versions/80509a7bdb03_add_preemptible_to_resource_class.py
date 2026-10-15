"""add preemptible flag to resource_classes

Revision ID: 80509a7bdb03
Revises: 3016b9c4de5e
Create Date: 2026-09-30 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "80509a7bdb03"
down_revision = "3016b9c4de5e"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | str | None = None


def upgrade() -> None:
    op.add_column(
        "resource_classes",
        sa.Column("preemptible", sa.Boolean(), nullable=False, server_default=sa.false()),
        schema="resource_pools",
    )


def downgrade() -> None:
    op.drop_column("resource_classes", "preemptible", schema="resource_pools")
