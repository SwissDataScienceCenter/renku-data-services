"""add onedrive and dropbox provider

Revision ID: 4f0770734ad1
Revises: b8cbd62e85b9
Create Date: 2024-09-11 13:10:20.656162

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "4f0770734ad1"
down_revision = "b8cbd62e85b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE providerkind ADD VALUE 'onedrive'")
    op.execute("ALTER TYPE providerkind ADD VALUE 'dropbox'")


def downgrade() -> None:
    # NOTE: Postgres does not allow removing values from an enum
    pass
