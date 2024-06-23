"""create storage secret table

Revision ID: 9058bf0a1a12
Revises: 9c26ab37ff4c
Create Date: 2024-06-14 17:22:27.013665

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "9058bf0a1a12"
down_revision = "9c26ab37ff4c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cloud_storage_secrets",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("storage_id", sa.String(length=26), nullable=False),
        sa.Column("name", sa.String(length=99), nullable=False),
        sa.Column("secret_id", sa.String(length=26), nullable=False),
        sa.ForeignKeyConstraint(["storage_id"], ["storage.cloud_storage.storage_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["secret_id"], ["secrets.secrets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.users.keycloak_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "storage_id", "name", name="_unique_user_id_storage_id_name"),
        schema="storage",
    )
    op.create_index(
        op.f("ix_storage_cloud_storage_secrets_user_id_storage_id"),
        "cloud_storage_secrets",
        ["user_id", "storage_id"],
        unique=False,
        schema="storage",
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_storage_cloud_storage_secrets_user_id_storage_id"),
        table_name="cloud_storage_secrets",
        schema="storage",
    )
    op.drop_table("cloud_storage_secrets", schema="storage")
