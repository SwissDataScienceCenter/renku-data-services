"""Add ai_agents to build parameters

Revision ID: 9969d6945381
Revises: e4265957153e
Create Date: 2026-11-05 11:30:00.000000

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "9969d6945381"
down_revision = "e4265957153e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "build_parameters",
        sa.Column(
            "ai_agents", sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"), nullable=True
        ),
        schema="sessions",
    )


def downgrade() -> None:
    op.drop_column("build_parameters", "ai_agents", schema="sessions")
