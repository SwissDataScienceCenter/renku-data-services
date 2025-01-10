"""allow environments to be archived

Revision ID: d71f0f795d30
Revises: d1cdcbb2adc3
Create Date: 2025-01-10 07:50:44.144549

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "d71f0f795d30"
down_revision = "d1cdcbb2adc3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column(
        "environments",
        sa.Column("is_archived", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        schema="sessions",
    )
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column("environments", "is_archived", schema="sessions")
    # ### end Alembic commands ###
