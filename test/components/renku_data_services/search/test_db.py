"""Tests for the repository."""

import pytest
from ulid import ULID

from renku_data_services.authz.models import Visibility
from renku_data_services.base_models.core import NamespacePath, NamespaceSlug, ProjectPath, ProjectSlug
from renku_data_services.data_connectors.models import CloudStorageCore, DataConnector
from renku_data_services.migrations.core import run_migrations_for_app
from renku_data_services.namespace.models import ProjectNamespace, UserNamespace
from renku_data_services.search.db import SearchUpdatesRepo
from renku_data_services.search.models import DeleteDoc
from renku_data_services.solr.entity_documents import DataConnector as DataConnectorDoc
from renku_data_services.solr.entity_documents import User as UserDoc
from renku_data_services.users.models import UserInfo

user_namespace = UserNamespace(
    id=ULID(),
    created_by="userid_2",
    underlying_resource_id=str(ULID()),
    path=NamespacePath.from_strings("user"),
)
project_namespace = ProjectNamespace(
    id=ULID(),
    created_by="user_id_3",
    path=ProjectPath(NamespaceSlug("hello-word"), ProjectSlug("project-1")),
    underlying_resource_id=ULID(),
)


@pytest.mark.asyncio
async def test_data_connector_within_project(app_manager_instance):
    run_migrations_for_app("common")
    repo = SearchUpdatesRepo(app_manager_instance.config.db.async_session_maker)
    dc = DataConnector(
        id=ULID(),
        name="my greater dc",
        storage=CloudStorageCore(
            storage_type="s3", configuration={}, source_path="/a", target_path="/b", readonly=True
        ),
        slug="dc-2",
        visibility=Visibility.PUBLIC,
        created_by="user_id_3",
        namespace=project_namespace,
    )
    orm_id = await repo.upsert(dc, started_at=None)
    db_doc = await repo.find_by_id(orm_id)
    if db_doc is None:
        raise Exception("dataconnector not found")
    dc_from_payload = DataConnectorDoc.from_dict(db_doc.payload)
    assert dc.id == dc_from_payload.id
    assert dc.name == dc_from_payload.name
    assert dc.path.serialize() == dc_from_payload.path
    assert dc.creation_date.replace(microsecond=0) == dc_from_payload.creationDate
    assert dc.visibility == dc_from_payload.visibility
    assert dc.slug == dc_from_payload.slug.value
    assert dc.storage.storage_type == dc_from_payload.storageType


@pytest.mark.asyncio
async def test_data_connector_upsert(app_manager_instance):
    run_migrations_for_app("common")
    repo = SearchUpdatesRepo(app_manager_instance.config.db.async_session_maker)
    dc = DataConnector(
        id=ULID(),
        name="mygreat dc",
        storage=CloudStorageCore(
            storage_type="s3", configuration={}, source_path="/a", target_path="/b", readonly=True
        ),
        slug="dc-1",
        visibility=Visibility.PUBLIC,
        created_by="userid_2",
        namespace=user_namespace,
    )
    orm_id = await repo.upsert(dc, started_at=None)
    db_doc = await repo.find_by_id(orm_id)
    if db_doc is None:
        raise Exception("dataconnector not found")
    dc_from_payload = DataConnectorDoc.from_dict(db_doc.payload)
    assert dc.id == dc_from_payload.id
    assert dc.name == dc_from_payload.name
    assert dc.path.serialize() == dc_from_payload.path
    assert dc.creation_date.replace(microsecond=0) == dc_from_payload.creationDate
    assert dc.visibility == dc_from_payload.visibility
    assert dc.slug == dc_from_payload.slug.value
    assert dc.storage.storage_type == dc_from_payload.storageType


@pytest.mark.asyncio
async def test_delete_doc(app_manager_instance):
    run_migrations_for_app("common")
    repo = SearchUpdatesRepo(app_manager_instance.config.db.async_session_maker)
    doc = DeleteDoc.user("user1234")
    orm_id = await repo.upsert(doc)
    db_doc = await repo.find_by_id(orm_id)
    assert db_doc is not None
    assert db_doc.entity_type == "User"
    assert db_doc.payload == {"id": "user1234", "deleted": True}


@pytest.mark.asyncio
async def test_user_upsert(app_manager_instance):
    run_migrations_for_app("common")
    repo = SearchUpdatesRepo(app_manager_instance.config.db.async_session_maker)
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
async def test_user_insert_only(app_manager_instance):
    run_migrations_for_app("common")
    repo = SearchUpdatesRepo(app_manager_instance.config.db.async_session_maker)
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


async def test_select_next(app_manager_instance):
    run_migrations_for_app("common")

    repo = SearchUpdatesRepo(app_manager_instance.config.db.async_session_maker)
    user1 = UserInfo(id="user123", first_name="Tadej", last_name="Pogacar", namespace=user_namespace)
    id1 = await repo.insert(user1, started_at=None)
    user2 = UserInfo(id="user234", first_name="Greg", last_name="Lemond", namespace=user_namespace)
    id2 = await repo.insert(user2, started_at=None)

    records = await repo.select_next(10)
    assert len(records) == 2
    assert [e.id for e in records] == [id1, id2]

    records2 = await repo.select_next(10)
    assert len(records2) == 0


async def test_mark_processed(app_manager_instance):
    run_migrations_for_app("common")

    repo = SearchUpdatesRepo(app_manager_instance.config.db.async_session_maker)
    user1 = UserInfo(id="user123", first_name="Tadej", last_name="Pogacar", namespace=user_namespace)
    await repo.insert(user1, started_at=None)
    user2 = UserInfo(id="user234", first_name="Greg", last_name="Lemond", namespace=user_namespace)
    await repo.insert(user2, started_at=None)

    records = await repo.select_next(1)
    assert len(records) == 1

    await repo.mark_processed([e.id for e in records])
