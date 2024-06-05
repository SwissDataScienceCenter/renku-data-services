"""add tolerations and affinities

Revision ID: 3097ca05ce65
Revises: 0044b54a89b9
Create Date: 2023-09-11 20:01:15.830659

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "3097ca05ce65"
down_revision = "0044b54a89b9"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | str | None = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table(
        "node_affinities",
        sa.Column("key", sa.String(length=63), nullable=False),
        sa.Column("resource_class_id", sa.Integer(), nullable=True),
        sa.Column("required_during_scheduling", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["resource_class_id"],
            ["resource_pools.resource_classes.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="resource_pools",
    )
    op.create_index(
        op.f("ix_resource_pools_node_affinities_resource_class_id"),
        "node_affinities",
        ["resource_class_id"],
        unique=False,
        schema="resource_pools",
    )
    op.create_table(
        "tolerations",
        sa.Column("key", sa.String(length=63), nullable=False),
        sa.Column("resource_class_id", sa.Integer(), nullable=True),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["resource_class_id"],
            ["resource_pools.resource_classes.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="resource_pools",
    )
    op.create_index(
        op.f("ix_resource_pools_tolerations_resource_class_id"),
        "tolerations",
        ["resource_class_id"],
        unique=False,
        schema="resource_pools",
    )
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index(
        op.f("ix_resource_pools_tolerations_resource_class_id"), table_name="tolerations", schema="resource_pools"
    )
    op.drop_table("tolerations", schema="resource_pools")
    op.drop_index(
        op.f("ix_resource_pools_node_affinities_resource_class_id"),
        table_name="node_affinities",
        schema="resource_pools",
    )
    op.drop_table("node_affinities", schema="resource_pools")
    # ### end Alembic commands ###