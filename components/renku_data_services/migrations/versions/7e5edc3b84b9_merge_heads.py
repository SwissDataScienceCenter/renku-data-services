"""merge heads

Revision ID: 7e5edc3b84b9
Revises: 04655faf7248, ce1a111d6694, 85447af3d0dd
Create Date: 2024-05-09 18:14:10.217776

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7e5edc3b84b9'
down_revision = ('04655faf7248', 'ce1a111d6694', '85447af3d0dd')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
