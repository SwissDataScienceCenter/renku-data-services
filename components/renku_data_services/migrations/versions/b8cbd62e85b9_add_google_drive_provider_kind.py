"""add google drive provider kind

Revision ID: b8cbd62e85b9
Revises: 9058bf0a1a12
Create Date: 2024-09-02 13:56:22.080007

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "b8cbd62e85b9"
down_revision = "9058bf0a1a12"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE providerkind ADD VALUE 'drive'")


def downgrade() -> None:
    # NOTE: Postgres does not allow removing values from an enum
    pass
