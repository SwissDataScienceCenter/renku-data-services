"""generate tables

Revision ID: 7c08ed2fb79d
Revises:
Create Date: 2023-11-09 18:29:12.832199

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "7c08ed2fb79d"
down_revision = None
branch_labels = ("projects",)
depends_on = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table(
        "projects",
        sa.Column("id", sa.String(26), nullable=False),
        sa.Column("name", sa.String(99), nullable=False),
        sa.Column("slug", sa.String(99), nullable=False),
        sa.Column("visibility", sa.Enum("public", "private", name="visibility"), nullable=False),
        sa.Column("created_by_id", sa.String(99), nullable=False),
        sa.Column("creation_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        schema="projects",
    )
    op.create_table(
        "projects_repositories",
        sa.Column("url", sa.String(2000), nullable=False),
        sa.Column("project_id", sa.String(26), nullable=True),
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.projects.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="projects",
    )
    op.create_index(
        op.f("ix_projects_projects_repositories_project_id"),
        "projects_repositories",
        ["project_id"],
        unique=False,
        schema="projects",
    )
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index(
        op.f("ix_projects_projects_repositories_project_id"), table_name="projects_repositories", schema="projects"
    )
    op.drop_table("projects_repositories", schema="projects")
    op.drop_table("projects", schema="projects")
    op.execute("DROP type visibility")
    # ### end Alembic commands ###
