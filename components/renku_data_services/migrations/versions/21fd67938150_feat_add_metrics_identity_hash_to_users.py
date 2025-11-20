"""feat: add metrics_identity_hash to users.

Revision ID: 21fd67938150
Revises: 5ea973da6921
Create Date: 2025-11-17 09:53:19.359423

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "21fd67938150"
down_revision = "5ea973da6921"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_metrics",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("metrics_identity_hash", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(
            ["id"],
            ["users.users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="users",
    )


def downgrade() -> None:
    op.drop_table("user_metrics", schema="users")
