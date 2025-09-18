"""feat: add support for remote sessions to resource pools

Revision ID: 3aa50593f4e4
Revises: fe61e825d95e
Create Date: 2025-09-18 13:31:32.392300

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "3aa50593f4e4"
down_revision = "fe61e825d95e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "resource_pools",
        sa.Column("remote", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        schema="resource_pools",
    )
    op.add_column(
        "resource_pools", sa.Column("remote_provider_id", sa.String(length=99), nullable=True), schema="resource_pools"
    )
    op.add_column(
        "resource_pools",
        sa.Column(
            "remote_configuration",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=True,
        ),
        schema="resource_pools",
    )
    op.create_index(
        op.f("ix_resource_pools_resource_pools_remote_provider_id"),
        "resource_pools",
        ["remote_provider_id"],
        unique=False,
        schema="resource_pools",
    )
    op.create_foreign_key(
        "resource_pools_remote_provider_id_fk",
        "resource_pools",
        "oauth2_clients",
        ["remote_provider_id"],
        ["id"],
        source_schema="resource_pools",
        referent_schema="connected_services",
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        "resource_pools_remote_provider_id_fk", "resource_pools", schema="resource_pools", type_="foreignkey"
    )
    op.drop_index(
        op.f("ix_resource_pools_resource_pools_remote_provider_id"),
        table_name="resource_pools",
        schema="resource_pools",
    )
    op.drop_column("resource_pools", "remote_configuration", schema="resource_pools")
    op.drop_column("resource_pools", "remote_provider_id", schema="resource_pools")
    op.drop_column("resource_pools", "remote", schema="resource_pools")
