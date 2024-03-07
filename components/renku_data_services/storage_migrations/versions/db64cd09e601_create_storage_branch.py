"""create storage branch

Revision ID: db64cd09e601
Revises: 61a4d72981cf
Create Date: 2024-03-07 20:29:09.023643

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'db64cd09e601'
down_revision = '61a4d72981cf'
branch_labels = ('storage',)
depends_on = None


def upgrade() -> None:
    schema = "storage"
    op.execute("CREATE SCHEMA IF NOT EXISTS common")
    op.execute(f"CREATE TABLE IF NOT EXISTS common.alembic_version (LIKE {schema}.alembic_version INCLUDING ALL)")
    op.execute(f"INSERT INTO common.alembic_version(version_num) VALUES ('{revision}')")


def downgrade() -> None:
    pass
