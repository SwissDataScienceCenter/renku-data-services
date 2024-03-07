"""create projects branch and copy version table

Revision ID: a74b8146d405
Revises: 7c08ed2fb79d
Create Date: 2024-03-07 20:21:49.311041

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a74b8146d405'
down_revision = '7c08ed2fb79d'
branch_labels = ('projects',)
depends_on = None


def upgrade() -> None:
    schema = "projects"
    op.execute("CREATE SCHEMA IF NOT EXISTS common")
    op.execute(f"CREATE TABLE IF NOT EXISTS common.alembic_version (LIKE {schema}.alembic_version INCLUDING ALL)")
    op.execute(f"INSERT INTO common.alembic_version(version_num) VALUES ('{revision}')")


def downgrade() -> None:
    pass
