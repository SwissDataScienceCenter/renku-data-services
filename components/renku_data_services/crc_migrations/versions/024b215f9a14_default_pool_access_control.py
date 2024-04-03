"""add default pool access control

Revision ID: 024b215f9a14
Revises: 3097ca05ce65
Create Date: 2023-1--15 12:33:45.53902

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.sql import expression

# revision identifiers, used by Alembic.
revision = "024b215f9a14"
down_revision = "3097ca05ce65"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | str | None = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column(
        "users",
        sa.Column("no_default_access", sa.Boolean(), nullable=False, default=False, server_default=expression.false()),
        schema="resource_pools",
    )
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column("users", "no_default_access", schema="resource_pools")
    # ### end Alembic commands ###
