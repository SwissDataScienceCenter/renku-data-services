"""squash me

Revision ID: fddfe7960a8b
Revises: 58ad5426c2f3
Create Date: 2026-01-21 11:52:05.169734

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "fddfe7960a8b"
down_revision = "58ad5426c2f3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE providerkind ADD VALUE 'dropbox'")


def downgrade() -> None:
    pass
