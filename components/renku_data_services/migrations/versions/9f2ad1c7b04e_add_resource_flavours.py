"""add_resource_flavours

Revision ID: 9f2ad1c7b04e
Revises: 21c885ddf188
Create Date: 2026-09-18 10:12:00.000000

"""

import sqlalchemy as sa
from alembic import op

from renku_data_services.utils.sqlalchemy import ULIDType

# revision identifiers, used by Alembic.
revision = "9f2ad1c7b04e"
down_revision = "21c885ddf188"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "resource_flavours",
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
        op.f("ix_resource_pools_resource_flavours_name"),
        "resource_flavours",
        ["name"],
        unique=True,
        schema="resource_pools",
    )
    op.add_column(
        "resource_classes",
        sa.Column("resource_flavour_id", ULIDType(), nullable=True),
        schema="resource_pools",
    )
    op.create_index(
        op.f("ix_resource_pools_resource_classes_resource_flavour_id"),
        "resource_classes",
        ["resource_flavour_id"],
        unique=False,
        schema="resource_pools",
    )
    op.create_foreign_key(
        "resource_classes_resource_flavour_id_fkey",
        "resource_classes",
        "resource_flavours",
        ["resource_flavour_id"],
        ["id"],
        source_schema="resource_pools",
        referent_schema="resource_pools",
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        "resource_classes_resource_flavour_id_fkey",
        "resource_classes",
        schema="resource_pools",
        type_="foreignkey",
    )
    op.drop_index(
        op.f("ix_resource_pools_resource_classes_resource_flavour_id"),
        table_name="resource_classes",
        schema="resource_pools",
    )
    op.drop_column("resource_classes", "resource_flavour_id", schema="resource_pools")
    op.drop_index(
        op.f("ix_resource_pools_resource_flavours_name"),
        table_name="resource_flavours",
        schema="resource_pools",
    )
    op.drop_table("resource_flavours", schema="resource_pools")
