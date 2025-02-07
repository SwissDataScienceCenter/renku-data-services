"""Tests for the repository."""

import pytest
from ulid import ULID

from renku_data_services.migrations.core import run_migrations_for_app
from renku_data_services.namespace.models import Namespace, NamespaceKind
from renku_data_services.search.db import SearchUpdatesRepo
from renku_data_services.solr.entity_documents import User as UserDoc
from renku_data_services.users.models import UserInfo

user_namespace = Namespace(
    id=ULID(), slug="test/user", kind=NamespaceKind.user, created_by="userid_2", underlying_resource_id=ULID()
)


@pytest.mark.asyncio
async def test_user_upsert(app_config_instance):
    run_migrations_for_app("common")
    repo = SearchUpdatesRepo(app_config_instance.db.async_session_maker)
    user = UserInfo(id="user123", first_name="Tadej", last_name="Pogacar", namespace=user_namespace)
    orm_id = await repo.upsert(user, started_at=None)

    user = UserInfo(id="user123", first_name="Tadej", last_name="Pogačar", namespace=user_namespace)
    orm_id2 = await repo.upsert(user, started_at=None)

    assert orm_id == orm_id2

    db_user = await repo.find_by_id(orm_id)
    if db_user is None:
        raise Exception("user not found")

    user = UserDoc.model_validate(db_user.payload)
    assert user.lastName == "Pogačar"


@pytest.mark.asyncio
async def test_user_insert_only(app_config_instance):
    run_migrations_for_app("common")
    repo = SearchUpdatesRepo(app_config_instance.db.async_session_maker)
    user = UserInfo(id="user123", first_name="Tadej", last_name="Pogacar", namespace=user_namespace)
    orm_id = await repo.insert(user, started_at=None)

    user = UserInfo(id="user123", first_name="Tadej", last_name="Pogačar", namespace=user_namespace)
    orm_id2 = await repo.insert(user, started_at=None)

    assert orm_id == orm_id2

    db_user = await repo.find_by_id(orm_id)
    if db_user is None:
        raise Exception("user not found")

    assert db_user.entity_type == "User"
    user = UserDoc.model_validate(db_user.payload)
    assert user.lastName == "Pogacar"
