"""add reprovisioning single row constraint

Revision ID: cefb45b5d71e
Revises: ce54fdbb40fe
Create Date: 2024-10-08 15:07:47.602432

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "cefb45b5d71e"
down_revision = "ce54fdbb40fe"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    # NOTE: This is a unique index on a constant value to make sure that only one row can exist in the table.
    op.create_index(
        op.f("ix_reprovisioning_single_row_constraint"),
        "reprovisioning",
        [sa.text("(( true ))")],
        unique=True,
        schema="events",
    )
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index(
        op.f("ix_reprovisioning_single_row_constraint"),
        table_name="reprovisioning",
        schema="events",
    )
    # ### end Alembic commands ###
