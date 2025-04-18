"""add template flag to projects

Revision ID: 08ac2714e8e2
Revises: 086eb60b42c8
Create Date: 2024-11-19 13:17:22.222365

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "08ac2714e8e2"
down_revision = "086eb60b42c8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column(
        "projects",
        sa.Column("is_template", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        schema="projects",
    )
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column("projects", "is_template", schema="projects")
    # ### end Alembic commands ###
