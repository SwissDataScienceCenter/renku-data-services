"""create authz branch and copy version table

Revision ID: 9a58a998ab79
Revises: 748ed0f3439f
Create Date: 2024-03-07 20:27:47.244416

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '9a58a998ab79'
down_revision = '748ed0f3439f'
branch_labels = ('authz',)
depends_on = None


def upgrade() -> None:
    schema = "authz"
    op.execute("CREATE SCHEMA IF NOT EXISTS common")
    op.execute(f"CREATE TABLE IF NOT EXISTS common.alembic_version (LIKE {schema}.alembic_version INCLUDING ALL)")
    op.execute(f"INSERT INTO common.alembic_version(version_num) VALUES ('{revision}')")


def downgrade() -> None:
    pass
