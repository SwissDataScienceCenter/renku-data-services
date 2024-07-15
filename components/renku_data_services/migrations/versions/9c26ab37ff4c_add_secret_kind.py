"""add secret kind

Revision ID: 9c26ab37ff4c
Revises: 6538ba654104
Create Date: 2024-06-06 16:41:56.948696

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "9c26ab37ff4c"
down_revision = "6538ba654104"
branch_labels = None
depends_on = None


def upgrade() -> None:
    secret_kind_enum = postgresql.ENUM("general", "storage", name="secretkind")
    secret_kind_enum.create(op.get_bind())
    op.add_column(
        "secrets", sa.Column("kind", secret_kind_enum, server_default="general", nullable=False), schema="secrets"
    )


def downgrade() -> None:
    op.drop_column("secrets", "kind", schema="secrets")
    op.execute("DROP TYPE secretkind")
