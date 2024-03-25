"""run missing migrations

Revision ID: bfdf48f5ed85
Revises: e16782d6bf32
Create Date: 2024-03-12 12:37:33.318543

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "bfdf48f5ed85"
down_revision = "e16782d6bf32"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_constraint(
        "projects_repositories_project_id_fkey", "projects_repositories", schema="projects", type_="foreignkey"
    )
    op.create_foreign_key(
        "projects_repositories_project_id_fkey_v2",
        "projects_repositories",
        "projects",
        ["project_id"],
        ["id"],
        source_schema="projects",
        referent_schema="projects",
        ondelete="CASCADE",
    )
    op.create_index(
        op.f("ix_resource_pools_node_affinities_key"), "node_affinities", ["key"], unique=False, schema="resource_pools"
    )
    op.create_index(
        op.f("ix_resource_pools_tolerations_key"), "tolerations", ["key"], unique=False, schema="resource_pools"
    )
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index(op.f("ix_resource_pools_tolerations_key"), table_name="tolerations", schema="resource_pools")
    op.drop_index(op.f("ix_resource_pools_node_affinities_key"), table_name="node_affinities", schema="resource_pools")
    op.drop_constraint(
        "projects_repositories_project_id_fkey_v2", "projects_repositories", schema="projects", type_="foreignkey"
    )
    op.create_foreign_key(
        "projects_repositories_project_id_fkey",
        "projects_repositories",
        "projects",
        ["project_id"],
        ["id"],
        source_schema="projects",
        referent_schema="projects",
    )
    # ### end Alembic commands ###
