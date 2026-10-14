"""add_resource_flavors

Revision ID: 9f2ad1c7b04e
Revises: fc1a97661d0c
Create Date: 2026-09-18 10:12:00.000000

"""

import sqlalchemy as sa
from alembic import op

from renku_data_services.utils.sqlalchemy import ULIDType

# revision identifiers, used by Alembic.
revision = "9f2ad1c7b04e"
down_revision = "fc1a97661d0c"
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


def downgrade() -> None:
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
