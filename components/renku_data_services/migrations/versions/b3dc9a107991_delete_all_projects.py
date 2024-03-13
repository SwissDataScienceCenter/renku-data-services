"""delete all projects

Revision ID: b3dc9a107991
Revises: bfdf48f5ed85
Create Date: 2024-03-13 10:42:32.176212

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b3dc9a107991'
down_revision = 'bfdf48f5ed85'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DELETE FROM projects.projects")


def downgrade() -> None:
    pass
