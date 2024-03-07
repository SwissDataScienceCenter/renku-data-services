"""create user_preferences branch and copy version table

Revision ID: 29a9eff96010
Revises: 6eccd7d4e3ed
Create Date: 2024-03-07 20:26:01.216312

"""
from alembic import op
import sqlalchemy as sa
from alembic import command

# revision identifiers, used by Alembic.
revision = '29a9eff96010'
down_revision = '6eccd7d4e3ed'
branch_labels = ('user_preferences',)
depends_on = None


def upgrade() -> None:
    schema = "user_preferences"
    op.execute("CREATE SCHEMA IF NOT EXISTS common")
    op.execute(f"CREATE TABLE IF NOT EXISTS common.alembic_version (LIKE {schema}.alembic_version INCLUDING ALL)")
    op.execute(f"INSERT INTO common.alembic_version(version_num) VALUES ('{revision}')")


def downgrade() -> None:
    pass
