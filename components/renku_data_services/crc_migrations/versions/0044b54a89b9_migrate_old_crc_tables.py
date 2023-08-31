"""migrate old crc tables

Revision ID: 0044b54a89b9
Revises: 95ce5418d4d9
Create Date: 2023-08-31 09:53:55.488210

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0044b54a89b9"
down_revision = "95ce5418d4d9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    result = connection.execute(
        sa.sql.text(
            """SELECT EXISTS (
                   SELECT FROM information_schema.tables
                   WHERE  table_schema = 'public'
                   AND    table_name   = 'resource_pools'
            );"""
        )
    )
    if not result.one()[0]:
        return

    statement = sa.sql.text(
        """
        INSERT INTO resource_pools.users
        SELECT *
        FROM public.users
        """
    )
    connection.execute(statement)

    statement = sa.sql.text(
        """
        INSERT INTO resource_pools.resource_pools
        SELECT *
        FROM public.resource_pools
        """
    )
    connection.execute(statement)
    statement = sa.sql.text(
        """
        INSERT INTO resource_pools.resource_classes
        SELECT *
        FROM public.resource_classes
        """
    )
    connection.execute(statement)
    statement = sa.sql.text(
        """
        INSERT INTO resource_pools.resource_pools_users
        SELECT *
        FROM public.resource_pools_users
        """
    )
    connection.execute(statement)

    op.drop_index(
        op.f("ix_resource_pools_resource_pools_users_user_id"),
        table_name="resource_pools_users",
        schema="public",
    )
    op.drop_index(
        op.f("ix_resource_pools_resource_pools_users_resource_pool_id"),
        table_name="resource_pools_users",
        schema="public",
    )
    op.drop_table("resource_pools_users", schema="public")
    op.drop_index(
        op.f("ix_resource_pools_resource_classes_resource_pool_id"),
        table_name="resource_classes",
        schema="public",
    )
    op.drop_index(op.f("ix_resource_pools_resource_classes_name"), table_name="resource_classes", schema="public")
    op.drop_table("resource_classes", schema="public")
    op.drop_index(op.f("ix_resource_pools_users_keycloak_id"), table_name="users", schema="public")
    op.drop_table("users", schema="public")
    op.drop_index(op.f("ix_resource_pools_resource_pools_quota"), table_name="resource_pools", schema="public")
    op.drop_index(op.f("ix_resource_pools_resource_pools_public"), table_name="resource_pools", schema="public")
    op.drop_index(op.f("ix_resource_pools_resource_pools_name"), table_name="resource_pools", schema="public")
    op.drop_index(op.f("ix_resource_pools_resource_pools_default"), table_name="resource_pools", schema="public")
    op.drop_table("resource_pools", schema="public")


def downgrade() -> None:
    pass
