"""create resource_pools branch

Revision ID: b6c2602737c9
Revises: 5403953f654f
Create Date: 2024-03-07 20:24:11.474212

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b6c2602737c9'
down_revision = '5403953f654f'
branch_labels = ('resource_pools',)
depends_on = None


def upgrade() -> None:
    schema = "resource_pools"
    op.execute("CREATE SCHEMA IF NOT EXISTS common")
    op.execute(f"CREATE TABLE IF NOT EXISTS common.alembic_version (LIKE {schema}.alembic_version INCLUDING ALL)")
    op.execute(f"INSERT INTO common.alembic_version(version_num) VALUES ('{revision}')")


def downgrade() -> None:
    pass
