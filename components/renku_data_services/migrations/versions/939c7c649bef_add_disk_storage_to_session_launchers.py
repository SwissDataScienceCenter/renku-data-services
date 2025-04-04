"""Add disk storage to session launchers

Revision ID: 939c7c649bef
Revises: d1cdcbb2adc3
Create Date: 2024-12-20 15:06:01.937878

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "939c7c649bef"
down_revision = "d1cdcbb2adc3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column("launchers", sa.Column("disk_storage", sa.BigInteger(), nullable=True), schema="sessions")
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column("launchers", "disk_storage", schema="sessions")
    # ### end Alembic commands ###
