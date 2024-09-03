"""namespace data connectors

Revision ID: c4ad57101cc8
Revises: a11752a5afba
Create Date: 2024-09-03 13:41:17.463220

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "c4ad57101cc8"
down_revision = "a11752a5afba"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("cloud_storage", "project_id", schema="storage", new_column_name="parent_id")
    op.execute("ALTER INDEX storage.ix_storage_cloud_storage_project_id RENAME TO ix_storage_cloud_storage_parent_id")
    cloud_storage_kind_enum = postgresql.ENUM("v1_cloud_storage", "v2_data_connector", name="cloudstoragekind")
    cloud_storage_kind_enum.create(op.get_bind())
    op.add_column(
        "cloud_storage",
        sa.Column("kind", cloud_storage_kind_enum, nullable=False, server_default="v1_cloud_storage"),
        schema="storage",
    )

    op.add_column("entity_slugs", sa.Column("cloud_storage_id", sa.String(length=26), nullable=True), schema="common")
    op.alter_column("entity_slugs", "project_id", existing_type=sa.VARCHAR(length=26), nullable=True, schema="common")
    op.create_index(
        op.f("ix_common_entity_slugs_cloud_storage_id"),
        "entity_slugs",
        ["cloud_storage_id"],
        unique=False,
        schema="common",
    )
    op.create_foreign_key(
        "entity_slugs_storage_id_fk",
        "entity_slugs",
        "cloud_storage",
        ["cloud_storage_id"],
        ["storage_id"],
        source_schema="common",
        referent_schema="storage",
        ondelete="CASCADE",
    )
    op.create_check_constraint(
        constraint_name="either_project_id_or_cloud_storage_id_is_set",
        condition="CAST (project_id IS NOT NULL AS int) + CAST (cloud_storage_id IS NOT NULL AS int) BETWEEN 0 AND 1",
        table_name="entity_slugs",
        schema="common",
    )


def downgrade() -> None:
    op.drop_constraint("either_project_id_or_cloud_storage_id_is_set", "entity_slugs", schema="common", type_="check")
    op.drop_constraint("entity_slugs_storage_id_fk", "entity_slugs", schema="common", type_="foreignkey")
    op.drop_index(op.f("ix_common_entity_slugs_cloud_storage_id"), table_name="entity_slugs", schema="common")
    op.alter_column("entity_slugs", "project_id", existing_type=sa.VARCHAR(length=26), nullable=False, schema="common")
    op.drop_column("entity_slugs", "cloud_storage_id", schema="common")

    op.drop_column("cloud_storage", "kind", schema="storage")
    op.execute("ALTER INDEX storage.ix_storage_cloud_storage_parent_id RENAME TO ix_storage_cloud_storage_project_id")
    op.alter_column("cloud_storage", "parent_id", schema="storage", new_column_name="project_id")
    op.execute("DROP TYPE cloudstoragekind")
