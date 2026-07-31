"""Tests for reprovision module."""

from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest
from ulid import ULID

from renku_data_services.authz.authz import Authz
from renku_data_services.authz.models import Visibility
from renku_data_services.base_models.core import APIUser, NamespacePath
from renku_data_services.base_models.metrics import MetricsService
from renku_data_services.data_connectors.db import DataConnectorRepository
from renku_data_services.data_connectors.models import (
    CloudStorageCore,
    DataConnector,
    GlobalDataConnector,
    UnsavedDataConnector,
)
from renku_data_services.message_queue.db import ReprovisioningRepository
from renku_data_services.migrations.core import run_migrations_for_app
from renku_data_services.namespace.db import GroupRepository
from renku_data_services.namespace.models import Group, UnsavedGroup, UserNamespace
from renku_data_services.project.db import ProjectRepository
from renku_data_services.project.models import Project, UnsavedProject
from renku_data_services.search.db import SearchUpdatesRepo
from renku_data_services.search.reprovision import SearchReprovision
from renku_data_services.users.db import UserRepo

admin = APIUser(id="the-admin-1", is_admin=True)
user_namespace = UserNamespace(
    id=ULID(),
    created_by="userid_2",
    underlying_resource_id=str(ULID()),
    path=NamespacePath.from_strings("user"),
)


@dataclass
class Setup:
    group_repo: GroupRepository
    user_repo: UserRepo
    project_repo: ProjectRepository
    data_connector_repo: DataConnectorRepository
    search_update_repo: SearchUpdatesRepo
    search_reprovision: SearchReprovision


def make_setup(app_manager_instance, solr_config) -> Setup:
    run_migrations_for_app("common")
    sess = app_manager_instance.config.db.async_session_maker
    search_updates = SearchUpdatesRepo(sess)
    authz = Authz(app_manager_instance.config.authz_config)
    gr = GroupRepository(sess, authz, search_updates)
    ur = UserRepo(sess, gr, search_updates, None, MagicMock(spec=MetricsService), authz)
    pr = ProjectRepository(sess, gr, search_updates, authz)
    dcr = DataConnectorRepository(sess, authz, pr, gr, search_updates)
    sr = SearchReprovision(
        search_updates_repo=search_updates,
        reprovisioning_repo=ReprovisioningRepository(sess),
        solr_config=solr_config,
        user_repo=ur,
        group_repo=gr,
        project_repo=pr,
        data_connector_repo=dcr,
    )
    return Setup(
        group_repo=gr,
        user_repo=ur,
        project_repo=pr,
        data_connector_repo=dcr,
        search_reprovision=sr,
        search_update_repo=search_updates,
    )


async def make_data_connectors(setup: Setup, count: int = 10) -> list[DataConnector]:
    user = await setup.user_repo.get_or_create_user(admin, "the-admin-1")
    if user is None:
        raise Exception("User not created")

    result = []
    for n in range(0, count):
        dc = UnsavedDataConnector(
            name=f"my dc {n}",
            visibility=Visibility.PUBLIC,
            created_by="me",
            slug=f"dc-{n}",
            namespace=user.namespace.path,
            storage=CloudStorageCore(
                storage_type="s3", configuration={}, source_path="a", target_path="b", readonly=True
            ),
        )
        dc = await setup.data_connector_repo.insert_namespaced_data_connector(admin, dc)
        result.append(dc)
    assert len(result) == count
    result.sort(key=lambda e: e.id)
    return result


async def make_groups(setup: Setup, count: int) -> list[Group]:
    result: list[Group] = []
    for n in range(0, count):
        g = UnsavedGroup(slug=f"group-{n}", name=f"Group name {n}")
        g = await setup.group_repo.insert_group(admin, g)
        result.append(g)

    result.sort(key=lambda e: e.id)
    return result


async def make_projects(setup: Setup, count: int) -> list[Project]:
    user = await setup.user_repo.get_or_create_user(admin, "the-admin-1")
    if user is None:
        raise Exception("User not created")

    result: list[Project] = []
    for n in range(0, count):
        p = UnsavedProject(
            name=f"project name {n}",
            slug=f"project-slug-{n}",
            visibility=Visibility.PUBLIC,
            created_by="me",
            namespace=user.namespace.path.serialize(),
        )
        p = await setup.project_repo.insert_project(admin, p)
        result.append(p)
    result.sort(key=lambda e: e.id)
    return result


async def get_all_connectors(setup: Setup, per_page: int) -> list[DataConnector | GlobalDataConnector]:
    result = [item async for item in setup.search_reprovision._get_all_data_connectors(admin, per_page=per_page)]
    result.sort(key=lambda e: e.id)
    return result


@pytest.mark.asyncio
async def test_get_data_connectors(app_manager_instance) -> None:
    setup = make_setup(app_manager_instance, solr_config={})
    inserted_dcs = await make_data_connectors(setup, 10)

    dcs = await get_all_connectors(setup, per_page=20)
    assert dcs == inserted_dcs

    dcs = await get_all_connectors(setup, per_page=10)
    assert dcs == inserted_dcs

    dcs = await get_all_connectors(setup, per_page=5)
    assert dcs == inserted_dcs

    dcs = await get_all_connectors(setup, per_page=3)
    assert dcs == inserted_dcs


@pytest.mark.asyncio
async def test_run_reprovision(app_manager_instance, solr_search, admin_user) -> None:
    setup = make_setup(app_manager_instance, solr_search)
    dcs = await make_data_connectors(setup, 5)
    groups = await make_groups(setup, 4)
    projects = await make_projects(setup, 3)
    users = [item async for item in setup.user_repo.get_all_users(admin)]

    count = await setup.search_reprovision.run_reprovision(admin_user)

    next = await setup.search_update_repo.select_next(20)

    user_orm = set()
    project_orm = set()
    group_orm = set()
    dc_orm = set()
    for e in next:
        match e.entity_type:
            case "Project":
                project_orm.add(e.entity_id)
            case "User":
                user_orm.add(e.entity_id)
            case "Group":
                group_orm.add(e.entity_id)
            case "DataConnector":
                dc_orm.add(e.entity_id)
            case _:
                raise Exception(f"entity type not handled: {e.entity_type}")

    assert count == (len(user_orm) + len(project_orm) + len(group_orm) + len(dc_orm))
    assert user_orm == {e.id for e in users}
    assert project_orm == {str(e.id) for e in projects}
    assert group_orm == {str(e.id) for e in groups}
    assert dc_orm == {str(e.id) for e in dcs}
