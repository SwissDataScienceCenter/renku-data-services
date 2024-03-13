"""create namespace tables

Revision ID: cd394c517556
Revises: b3dc9a107991
Create Date: 2024-03-13 11:07:42.988867

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "cd394c517556"
down_revision = "b3dc9a107991"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table(
        "namespaces",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(length=99), nullable=False),
        sa.Column("ltst_ns_slug_id", sa.Integer(), nullable=True),
        sa.Column("user_id", sa.String(length=36), nullable=True),
        sa.ForeignKeyConstraint(["ltst_ns_slug_id"], ["common.namespaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.users.keycloak_id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="common",
    )
    op.create_index(
        op.f("ix_common_namespaces_ltst_ns_slug_id"), "namespaces", ["ltst_ns_slug_id"], unique=False, schema="common"
    )
    op.create_index(op.f("ix_common_namespaces_slug"), "namespaces", ["slug"], unique=True, schema="common")
    op.create_index(op.f("ix_common_namespaces_user_id"), "namespaces", ["user_id"], unique=False, schema="common")
    op.create_table(
        "groups",
        sa.Column("id", sa.String(length=26), nullable=False),
        sa.Column("name", sa.String(length=99), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=False),
        sa.Column("creation_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ltst_ns_slug_id", sa.Integer(), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.users.keycloak_id"],
        ),
        sa.ForeignKeyConstraint(
            ["ltst_ns_slug_id"],
            ["common.namespaces.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="common",
    )
    op.create_index(op.f("ix_common_groups_created_by"), "groups", ["created_by"], unique=False, schema="common")
    op.create_index(op.f("ix_common_groups_name"), "groups", ["name"], unique=False, schema="common")
    op.create_table(
        "group_members",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("role", sa.Integer(), nullable=False),
        sa.Column("group_id", sa.String(length=26), nullable=False),
        sa.ForeignKeyConstraint(["group_id"], ["common.groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.users.keycloak_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema="common",
    )
    op.create_index(
        op.f("ix_common_group_members_group_id"), "group_members", ["group_id"], unique=False, schema="common"
    )
    op.create_table(
        "project_slugs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(length=99), nullable=False),
        sa.Column("ltst_ns_slug_id", sa.Integer(), nullable=True),
        sa.Column("ltst_prj_slug_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["ltst_ns_slug_id"], ["common.namespaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["ltst_prj_slug_id"], ["projects.project_slugs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema="projects",
    )
    op.create_index(
        op.f("ix_projects_project_slugs_ltst_ns_slug_id"),
        "project_slugs",
        ["ltst_ns_slug_id"],
        unique=False,
        schema="projects",
    )
    op.create_index(
        op.f("ix_projects_project_slugs_ltst_prj_slug_id"),
        "project_slugs",
        ["ltst_prj_slug_id"],
        unique=False,
        schema="projects",
    )
    op.create_index(op.f("ix_projects_project_slugs_slug"), "project_slugs", ["slug"], unique=False, schema="projects")
    op.create_index(
        "project_slugs_unique_slugs", "project_slugs", ["ltst_ns_slug_id", "slug"], unique=True, schema="projects"
    )
    op.add_column("projects", sa.Column("ltst_prj_slug_id", sa.Integer(), nullable=False), schema="projects")
    op.create_index(
        op.f("ix_projects_projects_ltst_prj_slug_id"), "projects", ["ltst_prj_slug_id"], unique=False, schema="projects"
    )
    op.create_foreign_key(
        "projects_latest_project_slug_id_fk",
        "projects",
        "project_slugs",
        ["ltst_prj_slug_id"],
        ["id"],
        source_schema="projects",
        referent_schema="projects",
    )
    op.drop_column("projects", "slug", schema="projects")
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column(
        "projects", sa.Column("slug", sa.VARCHAR(length=99), autoincrement=False, nullable=False), schema="projects"
    )
    op.drop_constraint("projects_latest_project_slug_id_fk", "projects", schema="projects", type_="foreignkey")
    op.drop_index(op.f("ix_projects_projects_ltst_prj_slug_id"), table_name="projects", schema="projects")
    op.drop_column("projects", "ltst_prj_slug_id", schema="projects")
    op.drop_index(op.f("ix_common_group_members_group_id"), table_name="group_members", schema="common")
    op.drop_table("group_members", schema="common")
    op.drop_index(op.f("ix_common_groups_name"), table_name="groups", schema="common")
    op.drop_index(op.f("ix_common_groups_created_by"), table_name="groups", schema="common")
    op.drop_table("groups", schema="common")
    op.drop_index(op.f("ix_common_namespaces_user_id"), table_name="namespaces", schema="common")
    op.drop_index(op.f("ix_common_namespaces_slug"), table_name="namespaces", schema="common")
    op.drop_index(op.f("ix_common_namespaces_ltst_ns_slug_id"), table_name="namespaces", schema="common")
    op.drop_table("namespaces", schema="common")
    op.drop_index("project_slugs_unique_slugs", table_name="project_slugs", schema="projects")
    op.drop_index(op.f("ix_projects_project_slugs_slug"), table_name="project_slugs", schema="projects")
    op.drop_index(op.f("ix_projects_project_slugs_ltst_prj_slug_id"), table_name="project_slugs", schema="projects")
    op.drop_index(op.f("ix_projects_project_slugs_ltst_ns_slug_id"), table_name="project_slugs", schema="projects")
    op.drop_table("project_slugs", schema="projects")
    # ### end Alembic commands ###