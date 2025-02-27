"""Add error_reason to image builds.

Revision ID: ed663f57179b
Revises: 71ef5efe740f
Create Date: 2025-02-27 11:39:29.912963

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "ed663f57179b"
down_revision = "71ef5efe740f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column("builds", sa.Column("error_reason", sa.String(length=500), nullable=True), schema="sessions")
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column("builds", "error_reason", schema="sessions")
    # ### end Alembic commands ###
