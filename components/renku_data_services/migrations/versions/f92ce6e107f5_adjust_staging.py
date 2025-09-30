"""adjust staging

Revision ID: f92ce6e107f5
Revises: 97de1962e448
Create Date: 2025-09-30 09:13:11.969526

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "f92ce6e107f5"
down_revision = "97de1962e448"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("resource_pools", "remote", schema="resource_pools")
    op.alter_column("resource_pools", "remote_configuration", new_column_name="remote_json", schema="resource_pools")


def downgrade() -> None:
    op.alter_column("resource_pools", "remote_json", new_column_name="remote_configuration", schema="resource_pools")
    op.add_column(
        "resource_pools",
        sa.Column("remote", sa.BOOLEAN(), server_default=sa.text("false"), autoincrement=False, nullable=False),
        schema="resource_pools",
    )
