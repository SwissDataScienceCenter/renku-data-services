"""Tests for sessions blueprints."""

from asyncio import AbstractEventLoop
from collections.abc import AsyncIterator, Coroutine
from typing import Any

import pytest
import pytest_asyncio
from pytest import FixtureRequest
from sanic_testing.testing import SanicASGITestClient, TestingResponse

from renku_data_services.app_config.config import Config
from renku_data_services.crc.apispec import ResourcePool
from renku_data_services.users.models import UserInfo


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
        if "environment" not in payload:
            payload["environment"] = {
                "environment_kind": "CUSTOM",
                "name": "Test",
                "container_image": "some_image:some_tag",
            }

        _, res = await sanic_client.post("/api/data/session_launchers", headers=user_headers, json=payload)

        assert res.status_code == 201, res.text
        assert res.json is not None
        return res.json

    return create_session_launcher_helper


@pytest.fixture
def launch_session(
    sanic_client: SanicASGITestClient,
    user_headers: dict,
    regular_user: UserInfo,
    app_config: Config,
    request: FixtureRequest,
    event_loop: AbstractEventLoop,
):
    async def launch_session_helper(
        payload: dict, headers: dict = user_headers, user: UserInfo = regular_user
    ) -> TestingResponse:
        _, res = await sanic_client.post("/api/data/sessions", headers=headers, json=payload)
        assert res.status_code == 201, res.text
        assert res.json is not None
        assert "name" in res.json
        session_id: str = res.json.get("name", "unknown")

        def cleanup():
            event_loop.run_until_complete(app_config.nb_config.k8s_v2_client.delete_server(session_id, user.id))

        # request.addfinalizer(cleanup)
        return res

    return launch_session_helper


@pytest.mark.asyncio
async def test_get_all_session_environments(
    sanic_client: SanicASGITestClient, unauthorized_headers, create_session_environment
) -> None:
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
) -> None:
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
async def test_post_session_environment(sanic_client: SanicASGITestClient, admin_headers) -> None:
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
async def test_post_session_environment_unauthorized(sanic_client: SanicASGITestClient, user_headers) -> None:
    payload = {
        "name": "Environment 1",
        "description": "A session environment.",
        "container_image": "some_image:some_tag",
    }

    _, res = await sanic_client.post("/api/data/environments", headers=user_headers, json=payload)

    assert res.status_code == 401, res.text


@pytest.mark.asyncio
async def test_patch_session_environment(
    sanic_client: SanicASGITestClient, admin_headers, create_session_environment
) -> None:
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
) -> None:
    env = await create_session_environment("Environment 1")
    environment_id = env["id"]

    payload = {
        "name": "New name",
        "description": "New description.",
        "container_image": "new_image:new_tag",
    }

    _, res = await sanic_client.patch(f"/api/data/environments/{environment_id}", headers=user_headers, json=payload)

    assert res.status_code == 403, res.text


@pytest.mark.asyncio
async def test_delete_session_environment(
    sanic_client: SanicASGITestClient, admin_headers, create_session_environment
) -> None:
    env = await create_session_environment("Environment 1")
    environment_id = env["id"]

    _, res = await sanic_client.delete(f"/api/data/environments/{environment_id}", headers=admin_headers)

    assert res.status_code == 204, res.text


@pytest.mark.asyncio
async def test_delete_session_environment_unauthorized(
    sanic_client: SanicASGITestClient, user_headers, create_session_environment
) -> None:
    env = await create_session_environment("Environment 1")
    environment_id = env["id"]

    _, res = await sanic_client.delete(f"/api/data/environments/{environment_id}", headers=user_headers)

    assert res.status_code == 403, res.text


@pytest.mark.asyncio
async def test_get_all_session_launchers(
    sanic_client: SanicASGITestClient,
    user_headers,
    create_project,
    create_session_launcher,
) -> None:
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
) -> None:
    project = await create_project("Some project", visibility="public")
    env = await create_session_environment("Some environment")
    launcher = await create_session_launcher(
        "Some launcher",
        project_id=project["id"],
        description="Some launcher.",
        environment={"id": env["id"]},
    )
    launcher_id = launcher["id"]

    _, res = await sanic_client.get(f"/api/data/session_launchers/{launcher_id}", headers=unauthorized_headers)

    assert res.status_code == 200, res.text
    assert res.json is not None
    assert res.json.get("name") == "Some launcher"
    assert res.json.get("project_id") == project["id"]
    assert res.json.get("description") == "Some launcher."
    environment = res.json.get("environment", {})
    assert environment.get("environment_kind") == "GLOBAL"
    assert environment.get("id") == env["id"]
    assert environment.get("container_image") == env["container_image"]
    assert res.json.get("resource_class_id") is None


@pytest.mark.asyncio
async def test_get_project_launchers(
    sanic_client: SanicASGITestClient,
    user_headers,
    create_project,
    create_session_launcher,
) -> None:
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
async def test_post_session_launcher(
    sanic_client: SanicASGITestClient,
    valid_resource_pool_payload: dict[str, Any],
    user_headers,
    admin_headers,
    member_1_headers,
    create_project,
    create_resource_pool,
) -> None:
    project = await create_project("Some project")
    resource_pool_data = valid_resource_pool_payload

    resource_pool = await create_resource_pool(admin=True, **resource_pool_data)

    payload = {
        "name": "Launcher 1",
        "project_id": project["id"],
        "description": "A session launcher.",
        "resource_class_id": resource_pool["classes"][0]["id"],
        "environment": {
            "container_image": "some_image:some_tag",
            "name": "custom_name",
            "environment_kind": "CUSTOM",
        },
    }

    _, res = await sanic_client.post("/api/data/session_launchers", headers=admin_headers, json=payload)

    assert res.status_code == 201, res.text
    assert res.json is not None
    assert res.json.get("name") == "Launcher 1"
    assert res.json.get("project_id") == project["id"]
    assert res.json.get("description") == "A session launcher."
    environment = res.json.get("environment", {})
    assert environment.get("environment_kind") == "CUSTOM"
    assert environment.get("container_image") == "some_image:some_tag"
    assert environment.get("id") is not None
    assert res.json.get("resource_class_id") == resource_pool["classes"][0]["id"]


@pytest.mark.asyncio
async def test_post_session_launcher_unauthorized(
    sanic_client: SanicASGITestClient,
    valid_resource_pool_payload: dict[str, Any],
    user_headers,
    admin_headers,
    create_project,
    create_resource_pool,
    regular_user,
    create_session_environment,
) -> None:
    project = await create_project("Some project")
    resource_pool_data = valid_resource_pool_payload
    resource_pool_data["public"] = False

    resource_pool = await create_resource_pool(admin=True, **resource_pool_data)
    environment = await create_session_environment("Test environment")

    payload = {
        "name": "Launcher 1",
        "project_id": project["id"],
        "description": "A session launcher.",
        "resource_class_id": resource_pool["classes"][0]["id"],
        "environment": {"id": environment["id"]},
    }

    _, res = await sanic_client.post("/api/data/session_launchers", headers=user_headers, json=payload)

    assert res.status_code == 403, res.text


@pytest.mark.asyncio
async def test_delete_session_launcher(
    sanic_client: SanicASGITestClient,
    user_headers,
    create_project,
    create_session_launcher,
) -> None:
    project = await create_project("Some project")
    launcher = await create_session_launcher("Launcher 1", project_id=project["id"])
    launcher_id = launcher["id"]

    _, res = await sanic_client.delete(f"/api/data/session_launchers/{launcher_id}", headers=user_headers)

    assert res.status_code == 204, res.text


@pytest.mark.asyncio
async def test_patch_session_launcher(
    sanic_client: SanicASGITestClient,
    valid_resource_pool_payload: dict[str, Any],
    user_headers,
    create_project,
    create_resource_pool,
) -> None:
    project = await create_project("Some project 1")
    resource_pool_data = valid_resource_pool_payload
    resource_pool = await create_resource_pool(admin=True, **resource_pool_data)

    payload = {
        "name": "Launcher 1",
        "project_id": project["id"],
        "description": "A session launcher.",
        "resource_class_id": resource_pool["classes"][0]["id"],
        "environment": {
            "container_image": "some_image:some_tag",
            "name": "custom_name",
            "environment_kind": "CUSTOM",
        },
    }

    _, res = await sanic_client.post("/api/data/session_launchers", headers=user_headers, json=payload)

    assert res.status_code == 201, res.text
    assert res.json is not None
    assert res.json.get("name") == "Launcher 1"
    assert res.json.get("description") == "A session launcher."
    environment = res.json.get("environment", {})
    assert environment.get("environment_kind") == "CUSTOM"
    assert environment.get("container_image") == "some_image:some_tag"
    assert environment.get("id") is not None
    assert res.json.get("resource_class_id") == resource_pool["classes"][0]["id"]

    patch_payload = {
        "name": "New Name",
        "description": "An updated session launcher.",
        "resource_class_id": resource_pool["classes"][1]["id"],
    }
    _, res = await sanic_client.patch(
        f"/api/data/session_launchers/{res.json['id']}", headers=user_headers, json=patch_payload
    )
    assert res.status_code == 200, res.text
    assert res.json is not None
    assert res.json.get("name") == patch_payload["name"]
    assert res.json.get("description") == patch_payload["description"]
    assert res.json.get("resource_class_id") == patch_payload["resource_class_id"]


@pytest.mark.asyncio
async def test_patch_session_launcher_environment(
    sanic_client: SanicASGITestClient,
    valid_resource_pool_payload: dict[str, Any],
    user_headers,
    create_project,
    create_resource_pool,
    create_session_environment,
) -> None:
    project = await create_project("Some project 1")
    resource_pool_data = valid_resource_pool_payload
    resource_pool = await create_resource_pool(admin=True, **resource_pool_data)
    global_env = await create_session_environment("Some environment")

    # Create a new custom environment with the launcher
    payload = {
        "name": "Launcher 1",
        "project_id": project["id"],
        "description": "A session launcher.",
        "resource_class_id": resource_pool["classes"][0]["id"],
        "environment": {
            "container_image": "some_image:some_tag",
            "name": "custom_name",
            "environment_kind": "CUSTOM",
        },
    }
    _, res = await sanic_client.post("/api/data/session_launchers", headers=user_headers, json=payload)
    assert res.status_code == 201, res.text
    assert res.json is not None
    environment = res.json.get("environment", {})
    assert environment.get("environment_kind") == "CUSTOM"
    assert environment.get("container_image") == "some_image:some_tag"
    assert environment.get("id") is not None

    # Patch in a global environment
    patch_payload = {
        "environment": {"id": global_env["id"]},
    }
    _, res = await sanic_client.patch(
        f"/api/data/session_launchers/{res.json['id']}", headers=user_headers, json=patch_payload
    )
    assert res.status_code == 200, res.text
    assert res.json is not None
    launcher_id = res.json["id"]
    global_env["environment_kind"] = "GLOBAL"
    assert res.json["environment"] == global_env

    # Trying to patch a field of the global environment should fail
    patch_payload = {
        "environment": {"container_image": "new_image"},
    }
    _, res = await sanic_client.patch(
        f"/api/data/session_launchers/{launcher_id}", headers=user_headers, json=patch_payload
    )
    assert res.status_code == 422, res.text

    # Patching in a wholly new custom environment over the global is allowed
    patch_payload = {
        "environment": {"container_image": "new_image", "name": "new_custom", "environment_kind": "CUSTOM"},
    }
    _, res = await sanic_client.patch(
        f"/api/data/session_launchers/{launcher_id}", headers=user_headers, json=patch_payload
    )
    assert res.status_code == 200, res.text


@pytest.fixture
def anonymous_user_headers() -> dict[str, str]:
    return {"Renku-Auth-Anon-Id": "some-random-value-1234"}


@pytest.mark.asyncio
async def test_starting_session_anonymous(
    sanic_client: SanicASGITestClient,
    create_project,
    create_session_launcher,
    user_headers,
    app_config: Config,
    admin_headers,
    launch_session,
    anonymous_user_headers,
) -> None:
    _, res = await sanic_client.post(
        "/api/data/resource_pools",
        json=ResourcePool.model_validate(app_config.default_resource_pool, from_attributes=True).model_dump(
            mode="json", exclude_none=True
        ),
        headers=admin_headers,
    )
    assert res.status_code == 201, res.text
    project: dict[str, Any] = await create_project(
        "Some project",
        visibility="public",
        repositories=["https://github.com/SwissDataScienceCenter/renku-data-services"],
    )
    launcher: dict[str, Any] = await create_session_launcher(
        "Launcher 1",
        project_id=project["id"],
        environment={
            "container_image": "renku/renkulab-py:3.10-0.23.0-amalthea-sessions-3",
            "environment_kind": "CUSTOM",
            "name": "test",
            "port": 8888,
        },
    )
    launcher_id = launcher["id"]
    project_id = project["id"]
    payload = {"project_id": project_id, "launcher_id": launcher_id}
    session_res = await launch_session(payload, headers=anonymous_user_headers)
    _, res = await sanic_client.get(f"/api/data/sessions/{session_res.json['name']}", headers=anonymous_user_headers)
    assert res.status_code == 200, res.text
    assert res.json["name"] == session_res.json["name"]
    _, res = await sanic_client.get("/api/data/sessions", headers=anonymous_user_headers)
    assert res.status_code == 200, res.text
    assert len(res.json) > 0
    assert session_res.json["name"] in [i["name"] for i in res.json]
    # Should be able to patch some fields of the custom environment
    patch_payload = {
        "environment": {"container_image": "nginx:latest"},
    }
    _, res = await sanic_client.patch(
        f"/api/data/session_launchers/{launcher_id}", headers=user_headers, json=patch_payload
    )
    assert res.status_code == 200, res.text
    assert res.json["environment"]["container_image"] == "nginx:latest"
