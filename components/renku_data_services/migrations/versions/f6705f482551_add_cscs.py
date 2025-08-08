"""add cscs

Revision ID: f6705f482551
Revises: f4ad62b7b323
Create Date: 2025-06-17 14:09:43.322460

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "f6705f482551"
down_revision = "f4ad62b7b323"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE providerkind ADD VALUE 'cscs'")


def downgrade() -> None:
    # NOTE: Postgres does not allow removing values from an enum
    pass
