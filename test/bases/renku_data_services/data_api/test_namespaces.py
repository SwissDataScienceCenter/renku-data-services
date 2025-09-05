import contextlib

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from renku_data_services.authz.models import Visibility
from renku_data_services.base_models.core import (
    AuthenticatedAPIUser,
    DataConnectorInProjectPath,
    DataConnectorPath,
    DataConnectorSlug,
    NamespacePath,
    ProjectPath,
    ProjectSlug,
)
from renku_data_services.data_api.dependencies import DependencyManager
from renku_data_services.data_connectors.models import (
    CloudStorageCore,
    DataConnector,
    DataConnectorPatch,
    GlobalDataConnector,
    UnsavedDataConnector,
)
from renku_data_services.errors.errors import ConflictError, MissingResourceError, ValidationError
from renku_data_services.namespace.models import UnsavedGroup
from renku_data_services.namespace.orm import EntitySlugORM
from renku_data_services.project.models import Project, ProjectPatch, UnsavedProject
from renku_data_services.users.models import UserInfo


@pytest.mark.asyncio
async def test_list_namespaces(sanic_client, user_headers, regular_user) -> None:
    payload = {
        "name": "Group1",
        "slug": "group-1",
        "description": "Group 1 Description",
    }
    _, response = await sanic_client.post("/api/data/groups", headers=user_headers, json=payload)
    assert response.status_code == 201, response.text
    _, response = await sanic_client.get("/api/data/namespaces", headers=user_headers)
    assert response.status_code == 200, response.text
    res_json = response.json
    assert len(res_json) == 2
    user_ns = res_json[0]
    assert user_ns["slug"] == "user.doe"
    assert user_ns.get("creation_date") is None
    assert user_ns["created_by"] == regular_user.id
    group_ns = res_json[1]
    assert group_ns["slug"] == "group-1"
    assert group_ns.get("creation_date") is not None
    assert group_ns["created_by"] == regular_user.id


@pytest.mark.asyncio
async def test_list_namespaces_pagination(sanic_client, user_headers) -> None:
    for idx in range(1, 7):
        payload = {"name": f"Group {idx}", "slug": f"group-{idx}"}
        _, response = await sanic_client.post("/api/data/groups", headers=user_headers, json=payload)
        assert response.status_code == 201, response.text

    _, response = await sanic_client.get("/api/data/namespaces?per_page=2", headers=user_headers)
    assert response.status_code == 200, response.text
    res_json = response.json
    assert len(res_json) == 2
    user_ns = res_json[0]
    assert user_ns["slug"] == "user.doe"
    group_ns = res_json[1]
    assert group_ns["slug"] == "group-1"
    assert response.headers.get("page") == "1"
    assert response.headers.get("per-page") == "2"
    assert response.headers.get("total") == "7"
    assert response.headers.get("total-pages") == "4"

    _, response = await sanic_client.get("/api/data/namespaces?per_page=2&page=4", headers=user_headers)
    assert response.status_code == 200, response.text
    res_json = response.json
    assert len(res_json) == 1
    user_ns = res_json[0]
    assert user_ns["slug"] == "group-6"
    assert response.headers.get("page") == "4"
    assert response.headers.get("per-page") == "2"
    assert response.headers.get("total") == "7"
    assert response.headers.get("total-pages") == "4"

    _, response = await sanic_client.get("/api/data/namespaces?per_page=1&page=3", headers=user_headers)
    assert response.status_code == 200, response.text
    res_json = response.json
    assert len(res_json) == 1
    user_ns = res_json[0]
    assert user_ns["slug"] == "group-2"
    assert response.headers.get("page") == "3"
    assert response.headers.get("per-page") == "1"
    assert response.headers.get("total") == "7"
    assert response.headers.get("total-pages") == "7"

    _, response = await sanic_client.get("/api/data/namespaces?per_page=5&page=1", headers=user_headers)
    assert response.status_code == 200, response.text
    res_json = response.json
    assert len(res_json) == 5
    user_ns = res_json[0]
    assert user_ns["slug"] == "user.doe"
    user_ns = res_json[4]
    assert user_ns["slug"] == "group-4"
    assert response.headers.get("page") == "1"
    assert response.headers.get("per-page") == "5"
    assert response.headers.get("total") == "7"
    assert response.headers.get("total-pages") == "2"

    _, response = await sanic_client.get("/api/data/namespaces?per_page=5&page=2", headers=user_headers)
    assert response.status_code == 200, response.text
    res_json = response.json
    assert len(res_json) == 2
    user_ns = res_json[0]
    assert user_ns["slug"] == "group-5"
    user_ns = res_json[1]
    assert user_ns["slug"] == "group-6"
    assert response.headers.get("page") == "2"
    assert response.headers.get("per-page") == "5"
    assert response.headers.get("total") == "7"
    assert response.headers.get("total-pages") == "2"


@pytest.mark.asyncio
async def test_list_namespaces_all_groups_are_public(sanic_client, user_headers, member_1_headers) -> None:
    payload = {
        "name": "Group 1",
        "slug": "group-1",
    }
    _, response = await sanic_client.post("/api/data/groups", headers=user_headers, json=payload)
    assert response.status_code == 201, response.text
    payload = {
        "name": "Group 2",
        "slug": "group-2",
    }
    _, response = await sanic_client.post("/api/data/groups", headers=member_1_headers, json=payload)
    assert response.status_code == 201, response.text

    _, response = await sanic_client.get("/api/data/namespaces", headers=user_headers)

    assert response.status_code == 200, response.text
    res_json = response.json
    assert len(res_json) == 3
    user_ns = res_json[0]
    assert user_ns["slug"] == "user.doe"
    group_1_ns = res_json[1]
    assert group_1_ns["slug"] == "group-1"
    group_2_ns = res_json[2]
    assert group_2_ns["slug"] == "group-2"


@pytest.mark.asyncio
async def test_list_namespaces_filter_minimum_role(sanic_client, user_headers, member_1_headers) -> None:
    payload = {
        "name": "Group 1",
        "slug": "group-1",
    }
    _, response = await sanic_client.post("/api/data/groups", headers=user_headers, json=payload)
    assert response.status_code == 201, response.text
    payload = {
        "name": "Group 2",
        "slug": "group-2",
    }
    _, response = await sanic_client.post("/api/data/groups", headers=member_1_headers, json=payload)
    assert response.status_code == 201, response.text
    payload = {
        "name": "Group 3",
        "slug": "group-3",
    }
    _, response = await sanic_client.post("/api/data/groups", headers=member_1_headers, json=payload)
    assert response.status_code == 201, response.text
    payload = {
        "name": "Group 4",
        "slug": "group-4",
    }
    _, response = await sanic_client.post("/api/data/groups", headers=member_1_headers, json=payload)
    assert response.status_code == 201, response.text
    new_members = [{"id": "user", "role": "viewer"}]
    _, response = await sanic_client.patch(
        "/api/data/groups/group-3/members", headers=member_1_headers, json=new_members
    )
    assert response.status_code == 200, response.text
    new_members = [{"id": "user", "role": "editor"}]
    _, response = await sanic_client.patch(
        "/api/data/groups/group-4/members", headers=member_1_headers, json=new_members
    )
    assert response.status_code == 200, response.text

    _, response = await sanic_client.get("/api/data/namespaces?minimum_role=viewer", headers=user_headers)

    assert response.status_code == 200, response.text
    res_json = response.json
    assert len(res_json) == 4
    user_ns = res_json[0]
    assert user_ns["slug"] == "user.doe"
    group_1_ns = res_json[1]
    assert group_1_ns["slug"] == "group-1"
    group_2_ns = res_json[2]
    assert group_2_ns["slug"] == "group-3"
    group_3_ns = res_json[3]
    assert group_3_ns["slug"] == "group-4"

    _, response = await sanic_client.get("/api/data/namespaces?minimum_role=editor", headers=user_headers)

    assert response.status_code == 200, response.text
    res_json = response.json
    assert len(res_json) == 3
    user_ns = res_json[0]
    assert user_ns["slug"] == "user.doe"
    group_1_ns = res_json[1]
    assert group_1_ns["slug"] == "group-1"
    group_2_ns = res_json[2]
    assert group_2_ns["slug"] == "group-4"

    _, response = await sanic_client.get("/api/data/namespaces?minimum_role=owner", headers=user_headers)

    assert response.status_code == 200, response.text
    res_json = response.json
    assert len(res_json) == 2
    user_ns = res_json[0]
    assert user_ns["slug"] == "user.doe"
    group_1_ns = res_json[1]
    assert group_1_ns["slug"] == "group-1"


@pytest.mark.asyncio
async def test_get_namespace_by_slug(sanic_client, user_headers) -> None:
    payload = {
        "name": "Group1",
        "slug": "group-1",
        "description": "Group 1 Description",
    }
    _, response = await sanic_client.post("/api/data/groups", headers=user_headers, json=payload)
    assert response.status_code == 201, response.text
    _, response = await sanic_client.get(f"/api/data/namespaces/{payload['slug']}", headers=user_headers)
    assert response.status_code == 200, response.text
    assert response.json["slug"] == payload["slug"]
    assert response.json["namespace_kind"] == "group"
    _, response = await sanic_client.get("/api/data/namespaces/user.doe", headers=user_headers)
    assert response.status_code == 200, response.text
    assert response.json["slug"] == "user.doe"
    assert response.json["namespace_kind"] == "user"


@pytest.mark.asyncio
async def test_get_namespace_by_slug_anonymously(sanic_client, user_headers) -> None:
    payload = {
        "name": "Group1",
        "slug": "group-1",
        "description": "Group 1 Description",
    }
    _, response = await sanic_client.post("/api/data/groups", headers=user_headers, json=payload)
    assert response.status_code == 201, response.text

    _, response = await sanic_client.get(f"/api/data/namespaces/{payload['slug']}")
    assert response.status_code == 200, response.text
    assert response.json["slug"] == payload["slug"]
    assert response.json["namespace_kind"] == "group"

    _, response = await sanic_client.get("/api/data/namespaces/user.doe")
    assert response.status_code == 200, response.text
    assert response.json["slug"] == "user.doe"
    assert response.json["namespace_kind"] == "user"


@pytest.mark.asyncio
async def test_entity_slug_uniqueness(sanic_client, user_headers) -> None:
    # Create a group i.e. /test1
    payload = {
        "name": "test1",
        "slug": "test1",
        "description": "Group 1 Description",
    }
    _, response = await sanic_client.post("/api/data/groups", headers=user_headers, json=payload)
    assert response.status_code == 201, response.text

    # A group with the same name cannot be created
    payload = {
        "name": "test-conflict",
        "slug": "user.doe",
        "description": "Group 1 Description",
    }
    _, response = await sanic_client.post("/api/data/groups", headers=user_headers, json=payload)
    assert response.status_code == 422, response.text

    # Create a project in the group /test1/test1
    payload = {
        "name": "test1",
        "namespace": "test1",
        "slug": "test1",
    }
    _, response = await sanic_client.post("/api/data/projects", headers=user_headers, json=payload)
    assert response.status_code == 201, response.text

    # Create a data connector in the project /test1/test1/test1
    payload = {
        "name": "test1",
        "namespace": "test1/test1",
        "slug": "test1",
        "storage": {
            "configuration": {"type": "s3", "endpoint": "http://s3.aws.com"},
            "source_path": "giab",
            "target_path": "giab",
        },
    }
    _, response = await sanic_client.post("/api/data/data_connectors", headers=user_headers, json=payload)
    assert response.status_code == 201, response.text

    # Creating the project again should fail because no slugs are free
    _, response = await sanic_client.post("/api/data/data_connectors", headers=user_headers, json=payload)
    assert response.status_code == 409, response.text

    # Create a data connector in the same project with a different name /test1/test1/test2
    payload = {
        "name": "test2",
        "namespace": "test1/test1",
        "slug": "test2",
        "storage": {
            "configuration": {"type": "s3", "endpoint": "http://s3.aws.com"},
            "source_path": "giab",
            "target_path": "giab",
        },
    }
    _, response = await sanic_client.post("/api/data/data_connectors", headers=user_headers, json=payload)
    assert response.status_code == 201, response.text

    # Create a new project in the same group with the same name as the data connector /test1/test2
    payload = {
        "name": "test2",
        "namespace": "test1",
        "slug": "test2",
    }
    _, response = await sanic_client.post("/api/data/projects", headers=user_headers, json=payload)
    assert response.status_code == 201, response.text

    # Trying to create a data connector with the same slug as the project in the same group should succeed
    # i.e. /test1/test2/test1 because the test2 project does not have a data connector called test1
    payload = {
        "name": "test1",
        "namespace": "test1/test2",
        "slug": "test1",
        "storage": {
            "configuration": {"type": "s3", "endpoint": "http://s3.aws.com"},
            "source_path": "giab",
            "target_path": "giab",
        },
    }
    _, response = await sanic_client.post("/api/data/data_connectors", headers=user_headers, json=payload)
    assert response.status_code == 201, response.text


@pytest.mark.asyncio
async def test_listing_project_namespaces(sanic_client, user_headers) -> None:
    # Create a group i.e. /test1
    payload = {
        "name": "test1",
        "slug": "test1",
        "description": "Group 1 Description",
    }
    _, response = await sanic_client.post("/api/data/groups", headers=user_headers, json=payload)
    assert response.status_code == 201, response.text

    # Create a project in the group /test1/test1
    payload = {
        "name": "proj1",
        "namespace": "test1",
        "slug": "proj1",
    }
    _, response = await sanic_client.post("/api/data/projects", headers=user_headers, json=payload)
    assert response.status_code == 201, response.text

    # Create a new project in the same group with the same name as the data connector /test1/test2
    payload = {
        "name": "proj2",
        "namespace": "test1",
        "slug": "proj2",
    }
    _, response = await sanic_client.post("/api/data/projects", headers=user_headers, json=payload)
    assert response.status_code == 201, response.text

    # If not defined by default you get only user and group namespaces
    _, response = await sanic_client.get("/api/data/namespaces", headers=user_headers)
    assert response.status_code == 200, response.text
    assert len(response.json) == 2

    # If requested then you should get all
    _, response = await sanic_client.get(
        "/api/data/namespaces", headers=user_headers, params={"kinds": ["group", "user", "project"]}
    )
    assert response.status_code == 200, response.text
    assert len(response.json) == 4

    # If requested only projects then you should get only projects
    _, response = await sanic_client.get("/api/data/namespaces", headers=user_headers, params={"kinds": ["project"]})
    assert response.status_code == 200, response.text
    assert len(response.json) == 2
    assert response.json[0]["name"] == "proj1"
    assert response.json[0]["namespace_kind"] == "project"
    assert response.json[0]["slug"] == "proj1"
    assert response.json[0]["path"] == "test1/proj1"
    assert response.json[1]["name"] == "proj2"
    assert response.json[1]["namespace_kind"] == "project"
    assert response.json[1]["slug"] == "proj2"
    assert response.json[1]["path"] == "test1/proj2"


@pytest.mark.asyncio
async def test_stored_procedure_cleanup_after_project_slug_deletion(
    create_project,
    user_headers,
    app_manager: DependencyManager,
    sanic_client,
    create_data_connector,
) -> None:
    # We use stored procedures to remove a project when its slug is removed
    proj = await create_project(name="test1")
    proj_id = proj.get("id")
    assert proj_id is not None
    namespace = proj.get("namespace")
    assert namespace is not None
    proj_slug = proj.get("slug")
    assert proj_slug is not None
    _, response = await sanic_client.get(f"/api/data/namespaces/{namespace}", headers=user_headers)
    assert response.status_code == 200
    dc = await create_data_connector(name="test-dc", namespace=f"{namespace}/{proj_slug}")
    dc_id = dc.get("id")
    assert dc_id is not None
    assert dc is not None
    async with app_manager.config.db.async_session_maker() as session, session.begin():
        # We do not have APIs exposed that will remove the slug so this is the only way to trigger this
        stmt = (
            select(EntitySlugORM)
            .where(EntitySlugORM.project_id == proj_id)
            .where(EntitySlugORM.namespace_id.is_not(None))
            .where(EntitySlugORM.data_connector_id.is_(None))
        )
        res = await session.scalar(stmt)
        assert res is not None
        await session.delete(res)
        await session.flush()
    # The project namespace is not there
    _, response = await sanic_client.get(f"/api/data/namespaces/{namespace}/{proj_slug}", headers=user_headers)
    assert response.status_code == 404
    # The user or group namespace is untouched
    _, response = await sanic_client.get(f"/api/data/namespaces/{namespace}", headers=user_headers)
    assert response.status_code == 200
    # The project and data connector are both gone
    _, response = await sanic_client.get(f"/api/data/projects/{proj_id}", headers=user_headers)
    assert response.status_code == 404
    _, response = await sanic_client.get(f"/api/data/data_connectors/{dc_id}", headers=user_headers)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_stored_procedure_cleanup_after_data_connector_slug_deletion(
    create_project,
    user_headers,
    app_manager: DependencyManager,
    sanic_client,
    create_data_connector,
) -> None:
    # We use stored procedures to remove a data connector when its slug is removed
    proj = await create_project(name="test1")
    proj_id = proj.get("id")
    assert proj_id is not None
    namespace = proj.get("namespace")
    assert namespace is not None
    proj_slug = proj.get("slug")
    assert proj_slug is not None
    _, response = await sanic_client.get(f"/api/data/namespaces/{namespace}", headers=user_headers)
    assert response.status_code == 200
    dc1 = await create_data_connector(name="test-dc", namespace=f"{namespace}/{proj_slug}")
    dc1_id = dc1.get("id")
    assert dc1_id is not None
    assert dc1 is not None
    dc2 = await create_data_connector(name="test-dc", namespace=namespace)
    dc2_id = dc2.get("id")
    assert dc2_id is not None
    assert dc2 is not None
    async with app_manager.config.db.async_session_maker() as session, session.begin():
        # We do not have APIs exposed that will remove the slug so this is the only way to trigger this
        stmt = select(EntitySlugORM).where(EntitySlugORM.data_connector_id == dc1_id)
        scalars = await session.scalars(stmt)
        res = scalars.one_or_none()
        assert res is not None
        await session.delete(res)
        stmt = select(EntitySlugORM).where(EntitySlugORM.data_connector_id == dc2_id)
        scalars = await session.scalars(stmt)
        res = scalars.one_or_none()
        assert res is not None
        await session.delete(res)
        await session.flush()
    # The project namespace is still there
    _, response = await sanic_client.get(f"/api/data/namespaces/{namespace}/{proj_slug}", headers=user_headers)
    assert response.status_code == 200
    # The user or group namespace is untouched
    _, response = await sanic_client.get(f"/api/data/namespaces/{namespace}", headers=user_headers)
    assert response.status_code == 200
    # The project is still there
    _, response = await sanic_client.get(f"/api/data/projects/{proj_id}", headers=user_headers)
    assert response.status_code == 200
    # The data connectors are gone
    _, response = await sanic_client.get(f"/api/data/data_connectors/{dc1_id}", headers=user_headers)
    assert response.status_code == 404
    _, response = await sanic_client.get(f"/api/data/data_connectors/{dc2_id}", headers=user_headers)
    assert response.status_code == 404


async def test_cleanup_with_group_deletion(
    create_project,
    create_group,
    user_headers,
    sanic_client,
    regular_user: UserInfo,
    create_data_connector,
) -> None:
    grp = await create_group("grp1")
    grp_id = grp.get("id")
    assert grp_id is not None
    grp_slug = grp.get("slug")
    assert grp_slug is not None
    prj = await create_project(name="prj1", namespace=grp_slug)
    prj_id = prj.get("id")
    assert prj_id is not None
    prj_slug = prj.get("slug")
    assert prj_slug is not None
    dc1 = await create_data_connector(name="dc1", namespace=grp_slug)
    dc1_id = dc1.get("id")
    assert dc1_id is not None
    dc2 = await create_data_connector(name="dc2", namespace=f"{grp_slug}/{prj_slug}")
    dc2_id = dc2.get("id")
    assert dc2_id is not None
    dc3 = await create_data_connector(name="dc3", namespace=regular_user.namespace.path.serialize())
    dc3_id = dc3.get("id")
    assert dc3_id is not None
    # Delete the group
    _, response = await sanic_client.delete(f"/api/data/groups/{grp_slug}", headers=user_headers)
    assert response.status_code == 204
    _, response = await sanic_client.get(f"/api/data/groups/{grp_slug}", headers=user_headers)
    assert response.status_code == 404
    # # The project namespace is not there
    _, response = await sanic_client.get(f"/api/data/namespaces/{grp_slug}/{prj_slug}", headers=user_headers)
    assert response.status_code == 404
    # The group namespace is not there
    _, response = await sanic_client.get(f"/api/data/namespaces/{grp_slug}", headers=user_headers)
    assert response.status_code == 404
    # The project is not there
    _, response = await sanic_client.get(f"/api/data/projects/{prj_id}", headers=user_headers)
    assert response.status_code == 404
    # The group and project data connectors are gone
    _, response = await sanic_client.get(f"/api/data/data_connectors/{dc1_id}", headers=user_headers)
    assert response.status_code == 404
    _, response = await sanic_client.get(f"/api/data/data_connectors/{dc2_id}", headers=user_headers)
    assert response.status_code == 404
    # The data connector in the user namespace is still there
    _, response = await sanic_client.get(f"/api/data/data_connectors/{dc3_id}", headers=user_headers)
    assert response.status_code == 200


def __project_patch_namespace(new_ns: str) -> ProjectPatch:
    return ProjectPatch(
        namespace=new_ns,
        name=None,
        slug=None,
        visibility=None,
        repositories=None,
        description=None,
        keywords=None,
        documentation=None,
        template_id=None,
        is_template=None,
        secrets_mount_directory=None,
    )


def __dc_patch_namespace(new_ns: ProjectPath | NamespacePath) -> DataConnectorPatch:
    return DataConnectorPatch(
        name=None,
        namespace=new_ns,
        slug=None,
        visibility=None,
        description=None,
        keywords=None,
        storage=None,
    )


def __dc_patch_slug(new_slug: str) -> DataConnectorPatch:
    return DataConnectorPatch(
        name=None,
        namespace=None,
        slug=new_slug,
        visibility=None,
        description=None,
        keywords=None,
        storage=None,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path1, path2, path2_patch, exc_type",
    [
        (
            ProjectPath.from_strings("grp1", "prj1"),
            ProjectPath.from_strings("grp2", "prj1"),
            __project_patch_namespace("grp1"),
            IntegrityError,
        ),
        (
            DataConnectorPath.from_strings("grp1", "dc1"),
            DataConnectorPath.from_strings("grp2", "dc1"),
            __dc_patch_namespace(NamespacePath.from_strings("grp1")),
            ValidationError,
        ),
        (
            DataConnectorInProjectPath.from_strings("grp1", "prj1", "dc1"),
            DataConnectorInProjectPath.from_strings("grp2", "prj1", "dc1"),
            __dc_patch_namespace(ProjectPath.from_strings("grp1", "prj1")),
            ValidationError,
        ),
        (
            DataConnectorInProjectPath.from_strings("grp1", "prj1", "dc1"),
            DataConnectorInProjectPath.from_strings("grp1", "prj2", "dc1"),
            __dc_patch_namespace(ProjectPath.from_strings("grp1", "prj1")),
            ValidationError,
        ),
        (
            DataConnectorInProjectPath.from_strings("grp1", "prj1", "dc1"),
            DataConnectorInProjectPath.from_strings("grp1", "prj1", "dc2"),
            __dc_patch_slug("dc1"),
            ValidationError,
        ),
        (
            DataConnectorPath.from_strings("grp1", "dc1"),
            DataConnectorPath.from_strings("grp1", "dc2"),
            __dc_patch_slug("dc1"),
            ValidationError,
        ),
    ],
)
async def test_avoiding_slug_conflicts_with_updates(
    sanic_client,
    app_manager_instance: DependencyManager,
    admin_user: UserInfo,
    admin_headers: dict[str, str],
    path1: ProjectPath | DataConnectorPath | DataConnectorInProjectPath,
    path2: ProjectPath | DataConnectorPath | DataConnectorInProjectPath,
    path2_patch: ProjectPatch | DataConnectorPatch,
    exc_type: type[Exception] | None,
) -> None:
    access_token = admin_headers.get("Authorization", "")[8:]
    user = AuthenticatedAPIUser(
        id=admin_user.id, access_token=access_token, email=admin_user.email or "user@google.com", is_admin=True
    )
    storage_config = CloudStorageCore(
        storage_type="",
        configuration={"type": "s3", "endpoint": "http://s3.aws.com"},
        source_path="giab",
        target_path="giab",
        readonly=False,
    )
    # Create groups
    await app_manager_instance.group_repo.insert_group(
        user, UnsavedGroup(name=path1.first.value, slug=path1.first.value)
    )
    try:
        await app_manager_instance.group_repo.get_group(user, path2.first)
    except MissingResourceError:
        await app_manager_instance.group_repo.insert_group(
            user, UnsavedGroup(name=path2.first.value, slug=path2.first.value)
        )
    prj2: Project | None = None
    dc2: DataConnector | GlobalDataConnector | None = None
    # Create first set of project and dc
    if isinstance(path1.second, ProjectSlug):
        await app_manager_instance.project_repo.insert_project(
            user,
            UnsavedProject(
                name=path1.second.value,
                slug=path1.second.value,
                created_by=user.id,
                visibility=Visibility.PUBLIC,
                namespace=path1.parent().serialize() if isinstance(path1, ProjectPath) else path1.first.value,
            ),
        )
    dc_slug_1: DataConnectorSlug | None = None
    if isinstance(path1, DataConnectorPath):
        dc_slug_1 = path1.second
    elif isinstance(path1, DataConnectorInProjectPath):
        dc_slug_1 = path1.third
    if dc_slug_1:
        await app_manager_instance.data_connector_repo.insert_namespaced_data_connector(
            user,
            UnsavedDataConnector(
                name=dc_slug_1.value,
                slug=dc_slug_1.value,
                visibility=Visibility.PUBLIC,
                created_by=user.id,
                storage=storage_config,
                namespace=path1.parent(),
            ),
        )
    # Create second set of project and dc
    if isinstance(path2.second, ProjectSlug):
        try:
            prj2 = await app_manager_instance.project_repo.insert_project(
                user,
                UnsavedProject(
                    name=path2.second.value,
                    slug=path2.second.value,
                    created_by=user.id,
                    visibility=Visibility.PUBLIC,
                    namespace=path2.first.value,
                ),
            )
        except ConflictError:
            prj2 = await app_manager_instance.project_repo.get_project_by_namespace_slug(
                user, path2.first.value, path2.second
            )
    dc_slug_2: DataConnectorSlug | None = None
    if isinstance(path2, DataConnectorPath):
        dc_slug_2 = path2.second
    elif isinstance(path2, DataConnectorInProjectPath):
        dc_slug_2 = path2.third
    if dc_slug_2:
        try:
            dc2 = await app_manager_instance.data_connector_repo.insert_namespaced_data_connector(
                user,
                UnsavedDataConnector(
                    name=dc_slug_2.value,
                    slug=dc_slug_2.value,
                    visibility=Visibility.PUBLIC,
                    created_by=user.id,
                    storage=storage_config,
                    namespace=path2.parent(),
                ),
            )
        except ConflictError:
            assert not isinstance(path2, ProjectPath)
            dc2 = await app_manager_instance.data_connector_repo.get_data_connector_by_slug(user, path2)
    # Test patches
    with pytest.raises(exc_type) if exc_type is not None else contextlib.nullcontext():
        if isinstance(path2_patch, ProjectPatch):
            assert prj2 is not None
            await app_manager_instance.project_repo.update_project(user, prj2.id, path2_patch)
        elif isinstance(path2_patch, DataConnectorPatch):
            assert dc2 is not None
            await app_manager_instance.data_connector_repo.update_data_connector(user, dc2.id, path2_patch, dc2.etag)
        else:
            raise AssertionError("No update was performed")
