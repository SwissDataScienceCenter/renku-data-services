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
    connection = op.get_bind()
    op.add_column("projects", sa.Column("secrets_mount_directory", sa.String(), nullable=True), schema="projects")

    # Force the `updated_at` column to be updated on all projects. This is done to invalidate all ETags.
    op.execute(sa.text("LOCK TABLE projects.projects IN EXCLUSIVE MODE"))
    touch_stmt = sa.update(sa.table("projects", sa.Column("updated_at"), schema="projects")).values(
        updated_at=sa.func.now()
    )
    connection.execute(touch_stmt)
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column("projects", "secrets_mount_directory", schema="projects")
    # ### end Alembic commands ###
