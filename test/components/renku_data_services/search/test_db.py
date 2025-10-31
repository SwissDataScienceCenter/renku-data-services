"""Tests for the repository."""

import uuid
from datetime import datetime

import pytest
from ulid import ULID

from renku_data_services.authz.models import Visibility
from renku_data_services.base_models import AuthenticatedAPIUser
from renku_data_services.base_models.core import (
    NamespacePath,
    NamespaceSlug,
    ProjectPath,
    ProjectSlug,
    Slug,
)
from renku_data_services.data_api.dependencies import DependencyManager
from renku_data_services.data_connectors.models import CloudStorageCore, DataConnector, UnsavedDataConnector
from renku_data_services.migrations.core import run_migrations_for_app
from renku_data_services.namespace.models import ProjectNamespace, UnsavedGroup, UserNamespace
from renku_data_services.project.models import UnsavedProject
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
async def test_remove_group_removes_descendant_entities(app_manager_instance: DependencyManager):
    run_migrations_for_app("common")
    repo = SearchUpdatesRepo(app_manager_instance.config.db.async_session_maker)
    user_repo = app_manager_instance.kc_user_repo
    group_repo = app_manager_instance.group_repo
    proj_repo = app_manager_instance.project_repo
    dc_repo = app_manager_instance.data_connector_repo

    user_id = uuid.uuid4()
    user = AuthenticatedAPIUser(id=str(user_id), access_token="abc")

    await user_repo.get_or_create_user(user, user.id)
    group = await group_repo.insert_group(user, UnsavedGroup(slug="group3", name="Group 3"))
    proj1 = await proj_repo.insert_project(
        user,
        UnsavedProject(
            namespace=group.slug,
            name="proj in group 1",
            slug="proj-group-1",
            visibility=Visibility.PUBLIC,
            created_by=user.id,
        ),
    )
    dc_in_proj = await dc_repo.insert_namespaced_data_connector(
        user,
        UnsavedDataConnector(
            name="dc 1",
            slug="dc1",
            visibility=Visibility.PUBLIC,
            created_by=user.id,
            namespace=proj1.path,
            storage=CloudStorageCore(
                storage_type="csc", configuration={}, source_path="", target_path="", readonly=True
            ),
        ),
    )
    dc_in_group = await dc_repo.insert_namespaced_data_connector(
        user,
        UnsavedDataConnector(
            name="dc 2",
            slug="dc2",
            visibility=Visibility.PUBLIC,
            created_by=user.id,
            namespace=group.path,
            storage=CloudStorageCore(
                storage_type="csc", configuration={}, source_path="", target_path="", readonly=True
            ),
        ),
    )

    updates = await repo.select_next(10)
    assert len(updates) == 5
    await repo.mark_processed([e.id for e in updates])

    # until here was preparation of the data. there is now a group,
    # containing a project and a data connector. the project also
    # contains a data connector

    deleted_group = await group_repo.delete_group(user, Slug.from_name(group.slug))
    assert deleted_group
    assert deleted_group.id == group.id

    updates = await repo.select_next(10)

    assert len(updates) == 4
    del_group = next(g for g in updates if g.entity_id == group.id)
    assert del_group.entity_type == "Group"
    assert del_group.payload["deleted"]

    del_proj = next(p for p in updates if p.entity_id == proj1.id)
    assert del_proj.entity_type == "Project"
    assert del_proj.payload["deleted"]

    del_dc1 = next(d for d in updates if d.entity_id == dc_in_proj.id)
    assert del_dc1.entity_type == "DataConnector"
    assert del_dc1.payload["deleted"]

    del_dc2 = next(d for d in updates if d.entity_id == dc_in_group.id)
    assert del_dc2.entity_type == "DataConnector"
    assert del_dc2.payload["deleted"]


@pytest.mark.asyncio
async def test_remove_project_removes_data_connector(app_manager_instance: DependencyManager):
    run_migrations_for_app("common")
    repo = SearchUpdatesRepo(app_manager_instance.config.db.async_session_maker)
    user_repo = app_manager_instance.kc_user_repo
    proj_repo = app_manager_instance.project_repo
    dc_repo = app_manager_instance.data_connector_repo

    user_id = uuid.uuid4()
    user = AuthenticatedAPIUser(id=str(user_id), access_token="abc", first_name="Huhu")

    u = await user_repo.get_or_create_user(user, user.id)
    assert u
    proj1 = await proj_repo.insert_project(
        user,
        UnsavedProject(
            namespace=u.namespace.path.first.value,
            name=f"proj of user {u.first_name}",
            slug="proj-group-1",
            visibility=Visibility.PUBLIC,
            created_by=user.id,
        ),
    )
    dc = await dc_repo.insert_namespaced_data_connector(
        user,
        UnsavedDataConnector(
            name="dc 1",
            slug="dc1",
            visibility=Visibility.PUBLIC,
            created_by=user.id,
            namespace=proj1.path,
            storage=CloudStorageCore(
                storage_type="csc", configuration={}, source_path="", target_path="", readonly=True
            ),
        ),
    )

    updates = await repo.select_next(10)
    assert len(updates) == 3
    await repo.mark_processed([e.id for e in updates])

    # until here was preparation of the data. there is now a group,
    # containing a project and a data connector. the project also
    # contains a data connector

    deleted_proj = await proj_repo.delete_project(user, proj1.id)
    assert deleted_proj
    assert deleted_proj.id == proj1.id

    updates = await repo.select_next(10)
    assert len(updates) == 2
    del_proj = next(p for p in updates if p.entity_id == proj1.id)
    assert del_proj.entity_type == "Project"
    assert del_proj.payload["deleted"]

    del_dc = next(d for d in updates if d.entity_id == dc.id)
    assert del_dc.entity_type == "DataConnector"
    assert del_dc.payload["deleted"]


@pytest.mark.asyncio
async def test_dc_in_group_project(app_manager_instance: DependencyManager) -> None:
    run_migrations_for_app("common")

    user_repo = app_manager_instance.kc_user_repo
    group_repo = app_manager_instance.group_repo
    proj_repo = app_manager_instance.project_repo
    dc_repo = app_manager_instance.data_connector_repo
    repo = SearchUpdatesRepo(app_manager_instance.config.db.async_session_maker)

    user = AuthenticatedAPIUser(id=str(uuid.uuid4()), access_token="abc", first_name="Huhu")
    u = await user_repo.get_or_create_user(user, user.id)
    assert u

    group = await group_repo.insert_group(user, UnsavedGroup(slug="grr1", name="Group Grr"))

    proj1 = await proj_repo.insert_project(
        user,
        UnsavedProject(
            namespace=group.slug,
            name=f"proj of group {group.name}",
            slug="proj-group-1",
            visibility=Visibility.PUBLIC,
            created_by=user.id,
        ),
    )
    dc_in_proj = await dc_repo.insert_namespaced_data_connector(
        user,
        UnsavedDataConnector(
            name="dc in group project",
            slug="dc2",
            visibility=Visibility.PUBLIC,
            created_by=user.id,
            namespace=proj1.path,
            storage=CloudStorageCore(
                storage_type="csc", configuration={}, source_path="", target_path="", readonly=True
            ),
        ),
    )
    dc_in_group = await dc_repo.insert_namespaced_data_connector(
        user,
        UnsavedDataConnector(
            name="dc in group",
            slug="dc1",
            visibility=Visibility.PUBLIC,
            created_by=user.id,
            namespace=group.path,
            storage=CloudStorageCore(
                storage_type="csc", configuration={}, source_path="", target_path="", readonly=True
            ),
        ),
    )

    updates = await repo.select_next(10)
    assert len(updates) == 5
    e1 = next(e for e in updates if e.entity_type == "User")
    assert e1.entity_id == user.id
    e2 = next(e for e in updates if e.entity_type == "Project")
    assert e2.entity_id == proj1.id
    e3 = next(e for e in updates if e.entity_type == "Group")
    assert e3.entity_id == group.id
    e45 = {e.entity_id for e in updates if e.entity_type == "DataConnector"}
    assert e45 == {str(dc_in_proj.id), str(dc_in_group.id)}


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
        updated_at=datetime.now(),
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
