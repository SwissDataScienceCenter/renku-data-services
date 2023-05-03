"""Create tables

Revision ID: f52872eca13f
Revises:
Create Date: 2023-05-02 23:35:56.698082

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "f52872eca13f"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table(
        "resource_pools",
        sa.Column("name", sa.String(length=40), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_resource_pools_name"), "resource_pools", ["name"], unique=False)
    op.create_table(
        "users",
        sa.Column("keycloak_id", sa.String(length=50), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_keycloak_id"), "users", ["keycloak_id"], unique=True)
    op.create_table(
        "quotas",
        sa.Column("cpu", sa.Float(), nullable=False),
        sa.Column("memory", sa.BigInteger(), nullable=False),
        sa.Column("storage", sa.BigInteger(), nullable=False),
        sa.Column("gpu", sa.BigInteger(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("resource_pool_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["resource_pool_id"], ["resource_pools.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_quotas_resource_pool_id"), "quotas", ["resource_pool_id"], unique=True)
    op.create_table(
        "resource_classes",
        sa.Column("name", sa.String(length=40), nullable=False),
        sa.Column("cpu", sa.Float(), nullable=False),
        sa.Column("memory", sa.BigInteger(), nullable=False),
        sa.Column("storage", sa.BigInteger(), nullable=False),
        sa.Column("gpu", sa.BigInteger(), nullable=False),
        sa.Column("resource_pool_id", sa.Integer(), nullable=True),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["resource_pool_id"], ["resource_pools.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_resource_classes_name"), "resource_classes", ["name"], unique=False)
    op.create_index(
        op.f("ix_resource_classes_resource_pool_id"), "resource_classes", ["resource_pool_id"], unique=False
    )
    op.create_table(
        "resource_pools_users",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("resource_pool_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["resource_pool_id"], ["resource_pools.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "resource_pool_id"),
    )
    op.create_index(
        op.f("ix_resource_pools_users_resource_pool_id"), "resource_pools_users", ["resource_pool_id"], unique=False
    )
    op.create_index(op.f("ix_resource_pools_users_user_id"), "resource_pools_users", ["user_id"], unique=False)
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index(op.f("ix_resource_pools_users_user_id"), table_name="resource_pools_users")
    op.drop_index(op.f("ix_resource_pools_users_resource_pool_id"), table_name="resource_pools_users")
    op.drop_table("resource_pools_users")
    op.drop_index(op.f("ix_resource_classes_resource_pool_id"), table_name="resource_classes")
    op.drop_index(op.f("ix_resource_classes_name"), table_name="resource_classes")
    op.drop_table("resource_classes")
    op.drop_index(op.f("ix_quotas_resource_pool_id"), table_name="quotas")
    op.drop_table("quotas")
    op.drop_index(op.f("ix_users_keycloak_id"), table_name="users")
    op.drop_table("users")
    op.drop_index(op.f("ix_resource_pools_name"), table_name="resource_pools")
    op.drop_table("resource_pools")
    # ### end Alembic commands ###
