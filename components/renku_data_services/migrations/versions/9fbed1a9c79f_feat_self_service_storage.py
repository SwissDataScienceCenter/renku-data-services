"""feat: self-service storage

Revision ID: 9fbed1a9c79f
Revises: e4265957153e
Create Date: 2026-11-06 10:45:57.325705

"""

import sqlalchemy as sa
from alembic import op

from renku_data_services.utils.sqlalchemy import ByteSizeType, PurePosixPathType, ULIDType

# revision identifiers, used by Alembic.
revision = "9fbed1a9c79f"
down_revision = "e4265957153e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Storage flavors
    op.create_table(
        "storage_flavors",
        sa.Column("id", ULIDType(), server_default=sa.text("generate_ulid()"), nullable=False),
        sa.Column("k8s_storage_class_name", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("min_size", ByteSizeType(), nullable=False),
        sa.Column("admin_documentation", sa.String(), nullable=True),
        sa.Column("documentation", sa.String(), nullable=True),
        sa.Column("creation_date", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        schema="resource_pools",
    )
    # Storage quotas
    op.create_table(
        "storage_quotas",
        sa.Column("id", ULIDType(), server_default=sa.text("generate_ulid()"), nullable=False),
        sa.Column("resource_pool_id", sa.Integer(), nullable=False),
        sa.Column("storage_flavor_id", ULIDType(), nullable=False),
        sa.Column("total_size", ByteSizeType(), nullable=False),
        sa.Column("max_size", ByteSizeType(), nullable=False),
        sa.Column("creation_date", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["resource_pool_id"], ["resource_pools.resource_pools.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["storage_flavor_id"], ["resource_pools.storage_flavors.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        schema="resource_pools",
    )
    op.create_index(
        op.f("ix_resource_pools_storage_quotas_resource_pool_id"),
        "storage_quotas",
        ["resource_pool_id"],
        unique=False,
        schema="resource_pools",
    )
    op.create_index(
        op.f("ix_resource_pools_storage_quotas_storage_flavor_id"),
        "storage_quotas",
        ["storage_flavor_id"],
        unique=False,
        schema="resource_pools",
    )
    # Project storages v2
    op.create_table(
        "project_storages_v2",
        sa.Column("id", ULIDType(), server_default=sa.text("generate_ulid()"), nullable=False),
        sa.Column("project_id", ULIDType(), nullable=False),
        sa.Column("storage_quota_id", ULIDType(), nullable=False),
        sa.Column("requested_size", ByteSizeType(), nullable=False),
        sa.Column("actual_size", ByteSizeType(), nullable=True),
        sa.Column("target_path", PurePosixPathType(), nullable=False),
        sa.Column("k8s_pvc_name", sa.String(), nullable=True),
        sa.Column("k8s_pvc_status", sa.String(), nullable=True),
        sa.Column("created_by_id", sa.String(length=36), nullable=False),
        sa.Column("creation_date", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.users.keycloak_id"],
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["storage_quota_id"], ["resource_pools.storage_quotas.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        schema="storage",
    )
    op.create_index(
        op.f("ix_storage_project_storages_v2_created_by_id"),
        "project_storages_v2",
        ["created_by_id"],
        unique=False,
        schema="storage",
    )
    op.create_index(
        op.f("ix_storage_project_storages_v2_project_id"),
        "project_storages_v2",
        ["project_id"],
        unique=True,
        schema="storage",
    )
    op.create_index(
        op.f("ix_storage_project_storages_v2_storage_quota_id"),
        "project_storages_v2",
        ["storage_quota_id"],
        unique=False,
        schema="storage",
    )


def downgrade() -> None:
    # Undo project storages v2
    op.drop_index(
        op.f("ix_storage_project_storages_v2_storage_quota_id"), table_name="project_storages_v2", schema="storage"
    )
    op.drop_index(op.f("ix_storage_project_storages_v2_project_id"), table_name="project_storages_v2", schema="storage")
    op.drop_index(
        op.f("ix_storage_project_storages_v2_created_by_id"), table_name="project_storages_v2", schema="storage"
    )
    op.drop_table("project_storages_v2", schema="storage")
    # Undo storage quotas
    op.drop_index(
        op.f("ix_resource_pools_storage_quotas_storage_flavor_id"), table_name="storage_quotas", schema="resource_pools"
    )
    op.drop_index(
        op.f("ix_resource_pools_storage_quotas_resource_pool_id"), table_name="storage_quotas", schema="resource_pools"
    )
    op.drop_table("storage_quotas", schema="resource_pools")
    # Undo storage flavors
    op.drop_table("storage_flavors", schema="resource_pools")
