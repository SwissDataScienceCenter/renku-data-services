"""add cascade to user_metrics

Revision ID: 4cbb36ac2a5c
Revises: bd97866a6253
Create Date: 2026-01-06 12:43:03.843315

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "4cbb36ac2a5c"
down_revision = "bd97866a6253"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("user_metrics_id_fkey", "user_metrics", schema="users", type_="foreignkey")
    op.create_foreign_key(
        "user_metrics_id_fkey",
        "user_metrics",
        "users",
        ["id"],
        ["id"],
        source_schema="users",
        referent_schema="users",
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("user_metrics_id_fkey", "user_metrics", schema="users", type_="foreignkey")
    op.create_foreign_key(
        "user_metrics_id_fkey", "user_metrics", "users", ["id"], ["id"], source_schema="users", referent_schema="users"
    )
