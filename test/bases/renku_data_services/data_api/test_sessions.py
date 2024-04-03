"""Tests for sessions blueprints."""

import json
from typing import Any

import pytest
from sanic_testing.testing import SanicASGITestClient

from renku_data_services.users.models import UserInfo


@pytest.fixture
def admin_user() -> UserInfo:
    return UserInfo("admin", "Admin", "Doe", "admin.doe@gmail.com")


@pytest.fixture
def regular_user() -> UserInfo:
    return UserInfo("user", "User", "Doe", "user.doe@gmail.com")


@pytest.fixture
def users(admin_user, regular_user) -> list[UserInfo]:
    return [
        admin_user,
        regular_user,
        UserInfo("member-1", "Member-1", "Doe", "member-1.doe@gmail.com"),
        UserInfo("member-2", "Member-2", "Doe", "member-2.doe@gmail.com"),
    ]


@pytest.fixture
def admin_headers(admin_user) -> dict[str, str]:
    """Authentication headers for an admin user."""
    access_token = json.dumps(
        {
            "is_admin": True,
            "id": admin_user.id,
            "name": f"{admin_user.first_name} {admin_user.last_name}",
        }
    )
    return {"Authorization": f"Bearer {access_token}"}


@pytest.fixture
def user_headers(regular_user) -> dict[str, str]:
    """Authentication headers for a normal user."""
    access_token = json.dumps(
        {
            "is_admin": False,
            "id": regular_user.id,
            "name": f"{regular_user.first_name} {regular_user.last_name}",
        }
    )
    return {"Authorization": f"Bearer {access_token}"}


@pytest.fixture
def unauthorized_headers() -> dict[str, str]:
    """Authentication headers for an anonymous user (did not log in)."""
    return {"Authorization": "Bearer {}"}


@pytest.fixture
def create_project(sanic_client, user_headers, admin_headers, regular_user, admin_user):
    async def create_project_helper(name: str, admin: bool = False, **payload) -> dict[str, Any]:
        headers = admin_headers if admin else user_headers
        user = admin_user if admin else regular_user
        payload = payload.copy()
        payload.update({"name": name, "namespace": f"{user.first_name}.{user.last_name}"})

        _, response = await sanic_client.post("/api/data/projects", headers=headers, json=payload)

        assert response.status_code == 201, response.text
        return response.json

    return create_project_helper


@pytest.fixture
def create_session_environment(sanic_client: SanicASGITestClient, admin_headers):
    async def create_session_environment_helper(name: str, **payload) -> dict[str, Any]:
        payload = payload.copy()
        payload.update({"name": name})
        payload["description"] = payload.get("description") or "A session environment."
        payload["container_image"] = payload.get("container_image") or "some_image:some_tag"

        _, res = await sanic_client.post("/api/data/environments", headers=admin_headers, json=payload)

        assert res.status_code == 201, res.text
        assert res.json is not None
        return res.json

    return create_session_environment_helper


@pytest.fixture
def create_session_launcher(sanic_client: SanicASGITestClient, user_headers):
    async def create_session_launcher_helper(name: str, project_id: str, **payload) -> dict[str, Any]:
        payload = payload.copy()
        payload.update({"name": name, "project_id": project_id})
        payload["description"] = payload.get("description") or "A session launcher."
        payload["environment_kind"] = payload.get("environment_kind") or "container_image"

        if payload["environment_kind"] == "container_image":
            payload["container_image"] = payload.get("container_image") or "some_image:some_tag"

        _, res = await sanic_client.post("/api/data/session_launchers", headers=user_headers, json=payload)

        assert res.status_code == 201, res.text
        assert res.json is not None
        return res.json

    return create_session_launcher_helper


@pytest.mark.asyncio
async def test_get_all_session_environments(
    sanic_client: SanicASGITestClient, unauthorized_headers, create_session_environment
):
    await create_session_environment("Environment 1")
    await create_session_environment("Environment 2")
    await create_session_environment("Environment 3")

    _, res = await sanic_client.get("/api/data/environments", headers=unauthorized_headers)

    assert res.status_code == 200, res.text
    assert res.json is not None
    environments = res.json
    assert {env["name"] for env in environments} == {
        "Environment 1",
        "Environment 2",
        "Environment 3",
    }


@pytest.mark.asyncio
async def test_get_session_environment(
    sanic_client: SanicASGITestClient, unauthorized_headers, create_session_environment
):
    env = await create_session_environment(
        "Environment 1",
        description="Some environment.",
        container_image="test_image:latest",
    )
    environment_id = env["id"]

    _, res = await sanic_client.get(f"/api/data/environments/{environment_id}", headers=unauthorized_headers)

    assert res.status_code == 200, res.text
    assert res.json is not None
    assert res.json.get("name") == "Environment 1"
    assert res.json.get("description") == "Some environment."
    assert res.json.get("container_image") == "test_image:latest"


@pytest.mark.asyncio
async def test_post_session_environment(sanic_client: SanicASGITestClient, admin_headers):
    payload = {
        "name": "Environment 1",
        "description": "A session environment.",
        "container_image": "some_image:some_tag",
    }

    _, res = await sanic_client.post("/api/data/environments", headers=admin_headers, json=payload)

    assert res.status_code == 201, res.text
    assert res.json is not None
    assert res.json.get("name") == "Environment 1"
    assert res.json.get("description") == "A session environment."
    assert res.json.get("container_image") == "some_image:some_tag"


@pytest.mark.asyncio
async def test_post_session_environment_unauthorized(sanic_client: SanicASGITestClient, user_headers):
    payload = {
        "name": "Environment 1",
        "description": "A session environment.",
        "container_image": "some_image:some_tag",
    }

    _, res = await sanic_client.post("/api/data/environments", headers=user_headers, json=payload)

    assert res.status_code == 401, res.text


@pytest.mark.asyncio
async def test_patch_session_environment(sanic_client: SanicASGITestClient, admin_headers, create_session_environment):
    env = await create_session_environment("Environment 1")
    environment_id = env["id"]

    payload = {
        "name": "New name",
        "description": "New description.",
        "container_image": "new_image:new_tag",
    }

    _, res = await sanic_client.patch(f"/api/data/environments/{environment_id}", headers=admin_headers, json=payload)

    assert res.status_code == 200, res.text
    assert res.json is not None
    assert res.json.get("name") == "New name"
    assert res.json.get("description") == "New description."
    assert res.json.get("container_image") == "new_image:new_tag"


@pytest.mark.asyncio
async def test_patch_session_environment_unauthorized(
    sanic_client: SanicASGITestClient, user_headers, create_session_environment
):
    env = await create_session_environment("Environment 1")
    environment_id = env["id"]

    payload = {
        "name": "New name",
        "description": "New description.",
        "container_image": "new_image:new_tag",
    }

    _, res = await sanic_client.patch(f"/api/data/environments/{environment_id}", headers=user_headers, json=payload)

    assert res.status_code == 401, res.text


@pytest.mark.asyncio
async def test_delete_session_environment(sanic_client: SanicASGITestClient, admin_headers, create_session_environment):
    env = await create_session_environment("Environment 1")
    environment_id = env["id"]

    _, res = await sanic_client.delete(f"/api/data/environments/{environment_id}", headers=admin_headers)

    assert res.status_code == 204, res.text


@pytest.mark.asyncio
async def test_delete_session_environment_unauthorized(
    sanic_client: SanicASGITestClient, user_headers, create_session_environment
):
    env = await create_session_environment("Environment 1")
    environment_id = env["id"]

    _, res = await sanic_client.delete(f"/api/data/environments/{environment_id}", headers=user_headers)

    assert res.status_code == 401, res.text


@pytest.mark.asyncio
async def test_get_all_session_launchers(
    sanic_client: SanicASGITestClient,
    user_headers,
    create_project,
    create_session_launcher,
):
    project_1 = await create_project("Project 1")
    project_2 = await create_project("Project 2")

    await create_session_launcher("Launcher 1", project_id=project_1["id"])
    await create_session_launcher("Launcher 2", project_id=project_2["id"])
    await create_session_launcher("Launcher 3", project_id=project_2["id"])

    _, res = await sanic_client.get("/api/data/session_launchers", headers=user_headers)

    assert res.status_code == 200, res.text
    assert res.json is not None
    launchers = res.json
    assert {launcher["name"] for launcher in launchers} == {
        "Launcher 1",
        "Launcher 2",
        "Launcher 3",
    }


@pytest.mark.asyncio
async def test_get_session_launcher(
    sanic_client: SanicASGITestClient,
    unauthorized_headers,
    create_project,
    create_session_environment,
    create_session_launcher,
):
    project = await create_project("Some project", visibility="public")
    env = await create_session_environment("Some environment")
    launcher = await create_session_launcher(
        "Some launcher",
        project_id=project["id"],
        description="Some launcher.",
        environment_kind="global_environment",
        environment_id=env["id"],
    )
    launcher_id = launcher["id"]

    _, res = await sanic_client.get(f"/api/data/session_launchers/{launcher_id}", headers=unauthorized_headers)

    assert res.status_code == 200, res.text
    assert res.json is not None
    assert res.json.get("name") == "Some launcher"
    assert res.json.get("project_id") == project["id"]
    assert res.json.get("description") == "Some launcher."
    assert res.json.get("environment_kind") == "global_environment"
    assert res.json.get("environment_id") == env["id"]
    assert res.json.get("container_image") is None


@pytest.mark.asyncio
async def test_get_project_launchers(
    sanic_client: SanicASGITestClient,
    user_headers,
    create_project,
    create_session_launcher,
):
    project_1 = await create_project("Project 1")
    project_2 = await create_project("Project 2")

    await create_session_launcher("Launcher 1", project_id=project_1["id"])
    await create_session_launcher("Launcher 2", project_id=project_2["id"])
    await create_session_launcher("Launcher 3", project_id=project_2["id"])

    _, res = await sanic_client.get(f"/api/data/projects/{project_2['id']}/session_launchers", headers=user_headers)

    assert res.status_code == 200, res.text
    assert res.json is not None
    launchers = res.json
    assert {launcher["name"] for launcher in launchers} == {"Launcher 2", "Launcher 3"}


@pytest.mark.asyncio
async def test_post_session_launcher(sanic_client: SanicASGITestClient, user_headers, create_project):
    project = await create_project("Some project")
    payload = {
        "name": "Launcher 1",
        "project_id": project["id"],
        "description": "A session launcher.",
        "environment_kind": "container_image",
        "container_image": "some_image:some_tag",
    }

    _, res = await sanic_client.post("/api/data/session_launchers", headers=user_headers, json=payload)

    assert res.status_code == 201, res.text
    assert res.json is not None
    assert res.json.get("name") == "Launcher 1"
    assert res.json.get("project_id") == project["id"]
    assert res.json.get("description") == "A session launcher."
    assert res.json.get("environment_kind") == "container_image"
    assert res.json.get("container_image") == "some_image:some_tag"
    assert res.json.get("environment_id") is None


@pytest.mark.asyncio
async def test_delete_session_launcher(
    sanic_client: SanicASGITestClient,
    user_headers,
    create_project,
    create_session_launcher,
):
    project = await create_project("Some project")
    launcher = await create_session_launcher("Launcher 1", project_id=project["id"])
    launcher_id = launcher["id"]

    _, res = await sanic_client.delete(f"/api/data/session_launchers/{launcher_id}", headers=user_headers)

    assert res.status_code == 204, res.text
