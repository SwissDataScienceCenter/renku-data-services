"""create resource_requests_limit table

Revision ID: 8084ed6e4502
Revises: ee31a5e627c7
Create Date: 2026-02-04 15:12:43.345762

"""

import sqlalchemy as sa
from alembic import op

from renku_data_services.utils.sqlalchemy import CreditType

# revision identifiers, used by Alembic.
revision = "8084ed6e4502"
down_revision = "ee31a5e627c7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "resource_requests_limits",
        sa.Column("resource_pool_id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column("total_limit", CreditType(), nullable=False),
        sa.Column("user_limit", CreditType(), nullable=False),
        schema="resource_pools",
    )
    op.create_foreign_key(
        "fk_resource_requests_limits_resource_pool_id",
        source_table="resource_requests_limits",
        referent_table="resource_pools",
        local_cols=["resource_pool_id"],
        remote_cols=["id"],
        referent_schema="resource_pools",
        source_schema="resource_pools",
        ondelete="cascade",
    )


def downgrade() -> None:
    op.drop_table("resource_requests_limits", schema="resource_pools")
