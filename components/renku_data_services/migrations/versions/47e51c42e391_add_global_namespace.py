"""Add global namespace

Revision ID: 47e51c42e391
Revises: dcb9648c3c15
Create Date: 2025-05-14 07:20:22.778969

"""

from alembic import op
from dataclasses import dataclass
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "47e51c42e391"
down_revision = "dcb9648c3c15"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    with connection.begin_nested() as tx:
        op.execute(sa.text("LOCK TABLE common.namespaces IN EXCLUSIVE MODE"))
        op.drop_constraint(
            "either_group_id_or_user_id_is_set",
            "namespaces",
            schema="common",
            type_="check",
        )
        op.create_check_constraint(
            "either_group_id_or_user_id_is_set",
            "namespaces",
            "(user_id IS NOT NULL) OR (group_id IS NOT NULL) OR (slug = '_global')",
            schema="common",
        )

        insert_global_namespace_stmt = (
            sa.insert(
                sa.table(
                    "namespaces",
                    sa.column("id", type_=sa.VARCHAR),
                    sa.column("slug", type_=sa.VARCHAR),
                    schema="common",
                )
            )
            .values(id=sa.text("generate_ulid()"), slug="_global")
            .returning(sa.column("id", type_=sa.VARCHAR))
        )
        namespace_id = connection.execute(insert_global_namespace_stmt).scalar()
        if not namespace_id:
            raise RuntimeError("Failed to insert the _global namespace")

        print(f"namespace_id={namespace_id}")

        op.execute(sa.text("LOCK TABLE storage.data_connectors IN EXCLUSIVE MODE"))
        select_global_data_connectors_stmt = (
            sa.select(sa.column("id", type_=sa.VARCHAR), sa.column("global_slug", type_=sa.VARCHAR))
            .select_from(sa.table("data_connectors", schema="storage"))
            .where(sa.column("global_slug", type_=sa.VARCHAR).is_not(sa.null()))
        )
        data_connectors = connection.execute(select_global_data_connectors_stmt).scalars().all()
        print(f"data_connectors={data_connectors}")

        for dc_id, dc_global_slug in data_connectors:
            insert_entity_slug_stmt = (
                sa.insert(
                    sa.table(
                        "entity_slugs",
                        sa.column("id", type_=sa.VARCHAR),
                        sa.column("slug", type_=sa.VARCHAR),
                        sa.column("data_connector_id", type_=sa.VARCHAR),
                        sa.column("namespace_id", type_=sa.VARCHAR),
                        schema="common",
                    )
                )
                .values(
                    id=sa.text("generate_ulid()"),
                    slug=dc_global_slug,
                    data_connector_id=dc_id,
                    namespace_id=namespace_id,
                )
                .returning(sa.column("id", type_=sa.VARCHAR))
            )
            slug_id = connection.execute(insert_entity_slug_stmt).scalar()
            if not slug_id:
                raise RuntimeError(f"Failed to insert the entity slug for data connector '{dc_id}'")

        tx.commit()


def downgrade() -> None:
    connection = op.get_bind()
    with connection.begin_nested() as tx:
        op.execute(sa.text("LOCK TABLE common.namespaces IN EXCLUSIVE MODE"))
        op.drop_constraint(
            "either_group_id_or_user_id_is_set",
            "namespaces",
            schema="common",
            type_="check",
        )
        op.create_check_constraint(
            "either_group_id_or_user_id_is_set",
            "namespaces",
            "(user_id IS NULL) <> (group_id IS NULL)",
            schema="common",
        )
        tx.commit()
    # CheckConstraint("(user_id IS NULL) <> (group_id IS NULL)", name="either_group_id_or_user_id_is_set"),
