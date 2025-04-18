"""create search update table

Revision ID: 64edf7ac0de0
Revises: 239854e7ea77
Create Date: 2025-02-20 11:55:42.824506

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from renku_data_services.utils.sqlalchemy import ULIDType

# revision identifiers, used by Alembic.
revision = "64edf7ac0de0"
down_revision = "239854e7ea77"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table(
        "search_updates",
        sa.Column("id", ULIDType(), server_default=sa.text("generate_ulid()"), nullable=False),
        sa.Column("entity_id", sa.String(length=100), nullable=False),
        sa.Column("entity_type", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "payload", sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"), nullable=False
        ),
        sa.Column("state", sa.Enum("Locked", "Failed", name="recordstate"), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        schema="events",
    )
    op.create_index(
        op.f("ix_events_search_updates_entity_id"), "search_updates", ["entity_id"], unique=True, schema="events"
    )
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index(op.f("ix_events_search_updates_entity_id"), table_name="search_updates", schema="events")
    op.drop_table("search_updates", schema="events")
    op.execute("drop type if exists recordstate")
    # ### end Alembic commands ###
