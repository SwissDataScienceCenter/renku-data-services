"""feat: self-service storage

Revision ID: 9fbed1a9c79f
Revises: e4265957153e
Create Date: 2026-11-06 10:45:57.325705

"""

import sqlalchemy as sa
from alembic import op

from renku_data_services.utils.sqlalchemy import ByteSizeType, ULIDType

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


def downgrade() -> None:
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
