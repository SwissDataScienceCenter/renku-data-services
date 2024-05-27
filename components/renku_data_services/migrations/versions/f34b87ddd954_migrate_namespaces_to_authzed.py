"""migrate namespaces to authzed

Revision ID: f34b87ddd954
Revises: d8676f0cde53
Create Date: 2024-05-22 07:56:17.839732

"""

import asyncio
from collections.abc import Coroutine
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, TypeVar

import sqlalchemy as sa
from alembic import op
from sqlalchemy.orm import Session

from renku_data_services.app_config.config import Config as AppConfig
from renku_data_services.message_queue.avro_models.io.renku.events import v2
from renku_data_services.message_queue.converters import EventConverter
from renku_data_services.message_queue.models import Event
from renku_data_services.namespace.orm import GroupORM, NamespaceORM
from renku_data_services.users.models import UserInfo, UserWithNamespace

# revision identifiers, used by Alembic.
revision = "f34b87ddd954"
down_revision = "d8676f0cde53"
branch_labels = None
depends_on = None

_T = TypeVar("_T")


def execute_coroutine(coro: Coroutine[Any, Any, _T]) -> _T:
    with ThreadPoolExecutor(1) as executor:
        future: Future[_T] = executor.submit(asyncio.run, coro)
        return future.result()

async def add_events(session: Session, app_config: AppConfig, events: list[Event]):
    for event in events:
        await app_config.event_repo.store_event(session, event)


def upgrade() -> None:
    app_config = AppConfig.from_env()
    authz_client = app_config.authz_config.authz_client()
    with Session(bind=op.get_bind()) as session, session.begin():
        # Delete all groups
        groups = session.scalars(sa.select(GroupORM)).all()
        for group in groups:
            session.delete(group)
            group_model = group.dump()
            events = EventConverter.to_events(group_model, v2.GroupRemoved)
            execute_coroutine(add_events(session, app_config, events))
        # Migrate user namespaces to authzed
        namespaces = session.scalars(sa.select(NamespaceORM)).all()
        for namespace in namespaces:
            authz_change = app_config.authz._add_user_namespace(namespace.dump())
            authz_client.WriteRelationships(authz_change.apply)
            if namespace.user is None:
                continue
            user_info = UserInfo(
                namespace.user.keycloak_id, namespace.user.first_name, namespace.user.last_name, namespace.user.email
            )
            user_w_namespace = UserWithNamespace(user_info, namespace.dump())
            events = EventConverter.to_events(user_w_namespace, v2.UserAdded)
            execute_coroutine(add_events(session, app_config, events))

    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index("ix_common_group_members_group_id", table_name="group_members", schema="common")
    op.drop_table("group_members", schema="common")
    op.drop_index("ix_users_secrets_user_id", table_name="secrets", schema="secrets")
    op.create_index(op.f("ix_secrets_secrets_user_id"), "secrets", ["user_id"], unique=False, schema="secrets")
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index(op.f("ix_secrets_secrets_user_id"), table_name="secrets", schema="secrets")
    op.create_index("ix_users_secrets_user_id", "secrets", ["user_id"], unique=False, schema="secrets")
    op.create_table(
        "group_members",
        sa.Column(
            "id",
            sa.INTEGER(),
            server_default=sa.text("nextval('common.group_members_id_seq'::regclass)"),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("user_id", sa.VARCHAR(length=36), autoincrement=False, nullable=False),
        sa.Column("role", sa.INTEGER(), autoincrement=False, nullable=False),
        sa.Column("group_id", sa.VARCHAR(length=26), autoincrement=False, nullable=False),
        sa.ForeignKeyConstraint(
            ["group_id"], ["common.groups.id"], name="group_members_group_id_fkey", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.users.keycloak_id"], name="group_members_user_id_fkey", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="group_members_pkey"),
        schema="common",
    )
    op.create_index("ix_common_group_members_group_id", "group_members", ["group_id"], unique=False, schema="common")
    # ### end Alembic commands ###
