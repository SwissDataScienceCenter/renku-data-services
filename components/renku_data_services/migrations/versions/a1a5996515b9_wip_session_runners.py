"""wip: session runners

Revision ID: a1a5996515b9
Revises: 274616d32338
Create Date: 2026-09-21 09:01:08.350576

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "a1a5996515b9"
down_revision = "274616d32338"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "assigned_sessions",
        sa.Column(
            "secrets",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            server_default=sa.text("NULL"),
            nullable=True,
        ),
        schema="session_runners",
    )


def downgrade() -> None:
    op.drop_column("assigned_sessions", "secrets", schema="session_runners")
