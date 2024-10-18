"""add google drive provider kind

Revision ID: b8cbd62e85b9
Revises: 726d5d0e1f28
Create Date: 2024-09-02 13:56:22.080007

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "b8cbd62e85b9"
down_revision = "726d5d0e1f28"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE providerkind ADD VALUE 'drive'")
    op.execute("ALTER TYPE providerkind ADD VALUE 'onedrive'")
    op.execute("ALTER TYPE providerkind ADD VALUE 'dropbox'")


def downgrade() -> None:
    # NOTE: Postgres does not allow removing values from an enum
    pass
