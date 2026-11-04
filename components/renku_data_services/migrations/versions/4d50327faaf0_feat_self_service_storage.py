"""feat: self-service storage

Revision ID: 4d50327faaf0
Revises: e4265957153e
Create Date: 2026-11-04 12:09:22.480389

"""

import sqlalchemy as sa
from alembic import op

from renku_data_services.utils.sqlalchemy import ByteSizeType

# revision identifiers, used by Alembic.
revision = "4d50327faaf0"
down_revision = "e4265957153e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "storage_classes",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("min_size", ByteSizeType(), nullable=False),
        sa.Column("admin_documentation", sa.String(), nullable=True),
        sa.Column("documentation", sa.String(), nullable=True),
        sa.Column("creation_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        schema="storage",
    )


def downgrade() -> None:
    op.drop_table("storage_classes", schema="storage")
