"""Add secrets_mount_directory to projects

Revision ID: d1cdcbb2adc3
Revises: a59e60e0338f
Create Date: 2024-11-27 14:34:45.594157

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "d1cdcbb2adc3"
down_revision = "a59e60e0338f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column("projects", sa.Column("secrets_mount_directory", sa.String(), nullable=True), schema="projects")
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column("projects", "secrets_mount_directory", schema="projects")
    # ### end Alembic commands ###
