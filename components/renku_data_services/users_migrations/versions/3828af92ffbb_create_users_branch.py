"""create users branch and copy version table

Revision ID: 3828af92ffbb
Revises: 3b30da432a76
Create Date: 2024-03-07 20:20:58.129381

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '3828af92ffbb'
down_revision = '3b30da432a76'
branch_labels = ('users',)
depends_on = None


def upgrade() -> None:
    schema = "users"
    op.execute("CREATE SCHEMA IF NOT EXISTS common")
    op.execute(f"CREATE TABLE IF NOT EXISTS common.alembic_version (LIKE {schema}.alembic_version INCLUDING ALL)")
    op.execute(f"INSERT INTO common.alembic_version(version_num) VALUES ('{revision}')")


def downgrade() -> None:
    pass
