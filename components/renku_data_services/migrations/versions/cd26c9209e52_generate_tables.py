"""generate tables

Revision ID: cd26c9209e52
Revises:
Create Date: 2024-02-29 08:15:40.140077

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "cd26c9209e52"
down_revision = None
branch_labels = ("sessions",)
depends_on = "7c08ed2fb79d"


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table(
        "environments",
        sa.Column("id", sa.String(length=26), nullable=False),
        sa.Column("name", sa.String(length=99), nullable=False),
        sa.Column("created_by_id", sa.String(), nullable=False),
        sa.Column("creation_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("container_image", sa.String(length=500), nullable=False),
        sa.Column("default_url", sa.String(length=200), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        schema="sessions",
    )
    op.create_table(
        "launchers",
        sa.Column("id", sa.String(length=26), nullable=False),
        sa.Column("name", sa.String(length=99), nullable=False),
        sa.Column("created_by_id", sa.String(), nullable=False),
        sa.Column("creation_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column(
            "environment_kind",
            sa.Enum("global_environment", "container_image", name="environmentkind", create_type=True),
            nullable=False,
        ),
        sa.Column("container_image", sa.String(length=500), nullable=True),
        sa.Column("default_url", sa.String(length=200), nullable=True),
        sa.Column("project_id", sa.String(length=26), nullable=False),
        sa.Column("environment_id", sa.String(length=26), nullable=True),
        sa.ForeignKeyConstraint(
            ["environment_id"],
            ["sessions.environments.id"],
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema="sessions",
    )
    op.create_index(
        op.f("ix_sessions_launchers_environment_id"), "launchers", ["environment_id"], unique=False, schema="sessions"
    )
    op.create_index(
        op.f("ix_sessions_launchers_project_id"), "launchers", ["project_id"], unique=False, schema="sessions"
    )
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index(op.f("ix_sessions_launchers_project_id"), table_name="launchers", schema="sessions")
    op.drop_index(op.f("ix_sessions_launchers_environment_id"), table_name="launchers", schema="sessions")
    op.drop_table("launchers", schema="sessions")
    op.drop_table("environments", schema="sessions")
    op.execute("DROP TYPE environmentkind")
    # ### end Alembic commands ###
