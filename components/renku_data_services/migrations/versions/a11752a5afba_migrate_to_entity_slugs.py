"""Migrate to entity slugs

Revision ID: a11752a5afba
Revises: 9058bf0a1a12
Create Date: 2024-09-03 11:18:46.025525

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "a11752a5afba"
down_revision = "9058bf0a1a12"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE projects.project_slugs SET SCHEMA common")
    op.rename_table("project_slugs", "entity_slugs", schema="common")
    op.execute("ALTER INDEX common.project_slugs_unique_slugs RENAME TO entity_slugs_unique_slugs")
    op.execute(
        "ALTER INDEX common.ix_projects_project_slugs_namespace_id RENAME TO ix_common_entity_slugs_namespace_id"
    )
    op.execute("ALTER INDEX common.ix_projects_project_slugs_project_id RENAME TO ix_common_entity_slugs_project_id")
    op.execute("ALTER INDEX common.ix_projects_project_slugs_slug RENAME TO ix_common_entity_slugs_slug")
    op.drop_constraint("project_slugs_project_id_fk", "entity_slugs", schema="common", type_="foreignkey")
    op.create_foreign_key(
        "entity_slugs_project_id_fk",
        "entity_slugs",
        "projects",
        ["project_id"],
        ["id"],
        source_schema="common",
        referent_schema="projects",
        ondelete="CASCADE",
    )

    op.execute("ALTER TABLE projects.project_slugs_old SET SCHEMA common")
    op.rename_table("project_slugs_old", "entity_slugs_old", schema="common")
    op.execute(
        "ALTER INDEX common.ix_projects_project_slugs_old_created_at RENAME TO ix_common_entity_slugs_old_created_at"
    )
    op.execute(
        "ALTER INDEX common.ix_projects_project_slugs_old_latest_slug_id RENAME TO ix_common_entity_slugs_old_latest_slug_id"
    )
    op.execute("ALTER INDEX common.ix_projects_project_slugs_old_slug RENAME TO ix_common_entity_slugs_old_slug")


def downgrade() -> None:
    op.drop_constraint("entity_slugs_project_id_fk", "entity_slugs", schema="common", type_="foreignkey")
    op.create_foreign_key(
        "project_slugs_project_id_fk",
        "entity_slugs",
        "projects",
        ["project_id"],
        ["id"],
        source_schema="common",
        referent_schema="projects",
        ondelete="CASCADE",
    )
    op.execute("ALTER INDEX common.ix_common_entity_slugs_slug RENAME TO ix_projects_project_slugs_slug")
    op.execute("ALTER INDEX common.ix_common_entity_slugs_project_id RENAME TO ix_projects_project_slugs_project_id")
    op.execute(
        "ALTER INDEX common.ix_common_entity_slugs_namespace_id RENAME TO ix_projects_project_slugs_namespace_id"
    )
    op.execute("ALTER INDEX common.entity_slugs_unique_slugs RENAME TO project_slugs_unique_slugs")
    op.rename_table("entity_slugs", "project_slugs", schema="common")
    op.execute("ALTER TABLE common.project_slugs SET SCHEMA projects")

    op.execute("ALTER INDEX common.ix_common_entity_slugs_old_slug RENAME TO ix_projects_project_slugs_old_slug")
    op.execute(
        "ALTER INDEX common.ix_common_entity_slugs_old_latest_slug_id RENAME TO ix_projects_project_slugs_old_latest_slug_id"
    )
    op.execute(
        "ALTER INDEX common.ix_common_entity_slugs_old_created_at RENAME TO ix_projects_project_slugs_old_created_at"
    )
    op.rename_table("entity_slugs_old", "project_slugs_old", schema="common")
    op.execute("ALTER TABLE common.project_slugs_old SET SCHEMA projects")
