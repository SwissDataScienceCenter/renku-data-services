"""add resource flavors

Revision ID: 20076b29e3b8
Revises: 80509a7bdb03
Create Date: 2026-10-19 08:57:20.221573

"""

import sqlalchemy as sa
from alembic import op

from renku_data_services.utils.sqlalchemy import ULIDType

# revision identifiers, used by Alembic.
revision = "20076b29e3b8"
down_revision = "80509a7bdb03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "resource_flavors",
        sa.Column("id", ULIDType(), nullable=False),
        sa.Column("name", sa.String(length=40), nullable=False),
        sa.Column("cpu", sa.Float(), nullable=False),
        sa.Column("memory", sa.BigInteger(), nullable=False),
        sa.Column("max_storage", sa.BigInteger(), nullable=False),
        sa.Column("default_storage", sa.BigInteger(), nullable=False),
        sa.Column("gpu", sa.BigInteger(), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        schema="resource_pools",
    )
    op.create_index(
        op.f("ix_resource_pools_resource_flavors_name"),
        "resource_flavors",
        ["name"],
        unique=True,
        schema="resource_pools",
    )
    op.add_column(
        "resource_classes",
        sa.Column("resource_flavor_id", ULIDType(), nullable=True),
        schema="resource_pools",
    )
    op.create_index(
        op.f("ix_resource_pools_resource_classes_resource_flavor_id"),
        "resource_classes",
        ["resource_flavor_id"],
        unique=False,
        schema="resource_pools",
    )
    op.create_foreign_key(
        "resource_classes_resource_flavor_id_fkey",
        "resource_classes",
        "resource_flavors",
        ["resource_flavor_id"],
        ["id"],
        source_schema="resource_pools",
        referent_schema="resource_pools",
        ondelete="RESTRICT",
    )
    op.alter_column(
        "resource_classes",
        "cpu",
        existing_type=sa.DOUBLE_PRECISION(precision=53),
        nullable=True,
        schema="resource_pools",
    )
    op.alter_column("resource_classes", "memory", existing_type=sa.BIGINT(), nullable=True, schema="resource_pools")
    op.alter_column(
        "resource_classes", "max_storage", existing_type=sa.BIGINT(), nullable=True, schema="resource_pools"
    )
    op.alter_column(
        "resource_classes", "default_storage", existing_type=sa.BIGINT(), nullable=True, schema="resource_pools"
    )
    op.alter_column("resource_classes", "gpu", existing_type=sa.BIGINT(), nullable=True, schema="resource_pools")
    op.create_check_constraint(
        condition="(resource_flavor_id IS NULL AND cpu IS NOT NULL AND memory IS NOT NULL AND max_storage IS NOT NULL "
        "AND default_storage IS NOT NULL AND gpu IS NOT NULL) "
        "OR (resource_flavor_id IS NOT NULL AND cpu IS NULL AND memory IS NULL AND max_storage IS NULL "
        "AND default_storage IS NULL AND gpu IS NULL)",
        constraint_name="chk_resource_flavor_or_values",
        table_name="resource_classes",
        schema="resource_pools",
    )


def downgrade() -> None:
    op.drop_constraint("chk_resource_flavor_or_values", "resource_classes", schema="resource_pools", type_="check")
    op.execute(
        "UPDATE resource_pools.resource_classes AS c "
        "SET cpu = f.cpu, memory = f.memory, max_storage = f.max_storage, "
        "default_storage = f.default_storage, gpu = f.gpu "
        "FROM resource_pools.resource_flavors AS f "
        "WHERE c.resource_flavor_id = f.id"
    )
    op.alter_column("resource_classes", "gpu", existing_type=sa.BIGINT(), nullable=False, schema="resource_pools")
    op.alter_column(
        "resource_classes", "default_storage", existing_type=sa.BIGINT(), nullable=False, schema="resource_pools"
    )
    op.alter_column(
        "resource_classes", "max_storage", existing_type=sa.BIGINT(), nullable=False, schema="resource_pools"
    )
    op.alter_column("resource_classes", "memory", existing_type=sa.BIGINT(), nullable=False, schema="resource_pools")
    op.alter_column(
        "resource_classes",
        "cpu",
        existing_type=sa.DOUBLE_PRECISION(precision=53),
        nullable=False,
        schema="resource_pools",
    )
    op.drop_constraint(
        "resource_classes_resource_flavor_id_fkey",
        "resource_classes",
        schema="resource_pools",
        type_="foreignkey",
    )
    op.drop_index(
        op.f("ix_resource_pools_resource_classes_resource_flavor_id"),
        table_name="resource_classes",
        schema="resource_pools",
    )
    op.drop_column("resource_classes", "resource_flavor_id", schema="resource_pools")
    op.drop_index(
        op.f("ix_resource_pools_resource_flavors_name"),
        table_name="resource_flavors",
        schema="resource_pools",
    )
    op.drop_table("resource_flavors", schema="resource_pools")
