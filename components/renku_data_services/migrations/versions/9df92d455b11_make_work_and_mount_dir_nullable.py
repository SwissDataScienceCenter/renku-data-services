"""make work and mount dir nullable

Revision ID: 9df92d455b11
Revises: ea52d750e389
Create Date: 2024-11-24 10:43:13.709187

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "9df92d455b11"
down_revision = "ea52d750e389"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.alter_column("environments", "working_directory", existing_type=sa.VARCHAR(), nullable=True, schema="sessions")
    op.alter_column("environments", "mount_directory", existing_type=sa.VARCHAR(), nullable=True, schema="sessions")
    # ### end Alembic commands ###


def downgrade() -> None:
    op.execute("UPDATE sessions.environments SET mount_directory = '/home/jovyan/work' WHERE mount_directory is NULL")
    op.execute(
        "UPDATE sessions.environments SET working_directory = '/home/jovyan/work' WHERE working_directory is NULL"
    )
    # ### commands auto generated by Alembic - please adjust! ###
    op.alter_column("environments", "mount_directory", existing_type=sa.VARCHAR(), nullable=False, schema="sessions")
    op.alter_column("environments", "working_directory", existing_type=sa.VARCHAR(), nullable=False, schema="sessions")
    # ### end Alembic commands ###
