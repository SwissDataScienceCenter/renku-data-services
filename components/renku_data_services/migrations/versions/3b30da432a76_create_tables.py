"""create tables

Revision ID: 3b30da432a76
Revises:
Create Date: 2023-11-23 13:04:29.168055

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "3b30da432a76"
down_revision: str | None = None
branch_labels = ("users",)
depends_on: Sequence[str] | str | None = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table(
        "last_keycloak_event_timestamp",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("timestamp_utc", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        schema="users",
    )
    op.create_table(
        "users",
        sa.Column("keycloak_id", sa.String(length=36), nullable=False),
        sa.Column("first_name", sa.String(length=256), nullable=True),
        sa.Column("last_name", sa.String(length=256), nullable=True),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        schema="users",
    )
    op.create_index(op.f("ix_users_users_email"), "users", ["email"], unique=False, schema="users")
    op.create_index(op.f("ix_users_users_keycloak_id"), "users", ["keycloak_id"], unique=True, schema="users")
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index(op.f("ix_users_users_keycloak_id"), table_name="users", schema="users")
    op.drop_index(op.f("ix_users_users_email"), table_name="users", schema="users")
    op.drop_table("users", schema="users")
    op.drop_table("last_keycloak_event_timestamp", schema="users")
    # ### end Alembic commands ###