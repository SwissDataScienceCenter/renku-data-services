"""Tests for sessions blueprints."""

from asyncio import AbstractEventLoop
from typing import Any

import pytest
from pytest import FixtureRequest
from sanic_testing.testing import SanicASGITestClient, TestingResponse
from syrupy.filters import props

from renku_data_services import errors
from renku_data_services.crc.apispec import ResourcePool
from renku_data_services.data_api.dependencies import DependencyManager
from renku_data_services.session.models import EnvVar
from renku_data_services.users.models import UserInfo


@pytest.fixture
def launch_session(
    sanic_client: SanicASGITestClient,
    user_headers: dict,
    regular_user: UserInfo,
    app_manager: DependencyManager,
    request: FixtureRequest,
    event_loop: AbstractEventLoop,
):
    async def launch_session_helper(
        payload: dict, headers: dict = None, user: UserInfo = regular_user
    ) -> TestingResponse:
        headers = headers or user_headers
        _, res = await sanic_client.post("/api/data/sessions", headers=headers, json=payload)
        assert res.status_code == 201, res.text
        assert res.json is not None
        assert "name" in res.json
        session_id: str = res.json.get("name", "unknown")

        def cleanup():
            event_loop.run_until_complete(
                app_manager.config.nb_config.k8s_v2_client.delete_session(session_id, user.id)
            )

        # request.addfinalizer(cleanup)
        return res

    return launch_session_helper


@pytest.mark.asyncio
async def test_get_all_session_environments(
    sanic_client: SanicASGITestClient, unauthorized_headers, create_session_environment, snapshot
) -> None:
    await create_session_environment("Environment 1")
    await create_session_environment("Environment 2")
    await create_session_environment("Environment 3")
    await create_session_environment("Environment 4", is_archived=True)

    _, res = await sanic_client.get("/api/data/environments", headers=unauthorized_headers)

    assert res.status_code == 200, res.text
    assert res.json is not None
    environments = res.json
    assert {env["name"] for env in environments} == {
        "Environment 1",
        "Environment 2",
        "Environment 3",
        "Python/Jupyter",  # environments added by bootstrap migration
        "Rstudio",
    }
    _, res = await sanic_client.get("/api/data/environments?include_archived=true", headers=unauthorized_headers)

    assert res.status_code == 200, res.text
    assert res.json is not None
    environments = res.json
    assert {env["name"] for env in environments} == {
        "Environment 1",
        "Environment 2",
        "Environment 3",
        "Environment 4",
        "Python/Jupyter",  # environments added by bootstrap migration
        "Rstudio",
    }
    assert environments == snapshot(exclude=props("id", "creation_date"))


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
@pytest.mark.parametrize(
    "image_name",
    [
        "renku/renku",
        "u/renku/renku:latest",
        "docker.io/renku/renku:latest",
        "renku/renku@sha256:eceed25752d7544db159e4144a41ed6e96e667f39ff9fa18322d79c33729a18c",
        "registry.renkulab.io/john.doe/test-34:38d8b3d",
    ],
)
async def test_post_session_environment(sanic_client: SanicASGITestClient, admin_headers, image_name: str) -> None:
    payload = {
        "name": "Environment 1",
        "description": "A session environment.",
        "container_image": image_name,
        "environment_image_source": "image",
    }

    _, res = await sanic_client.post("/api/data/environments", headers=admin_headers, json=payload)

    assert res.status_code == 201, res.text
    assert res.json is not None
    assert res.json.get("name") == "Environment 1"
    assert res.json.get("description") == "A session environment."
    assert res.json.get("container_image") == image_name
    assert not res.json.get("is_archived")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "image_name",
    [
        "https://example.com/r/test:latest",
        "renku/_bla",
        "renku/test:töst",
        "renku/test@sha254:abcd",
        " renku/test:latest",
    ],
)
async def test_post_session_environment_invalid_image(
    sanic_client: SanicASGITestClient, admin_headers, image_name: str
) -> None:
    payload = {
        "name": "Environment 1",
        "description": "A session environment.",
        "container_image": image_name,
    }

    _, res = await sanic_client.post("/api/data/environments", headers=admin_headers, json=payload)

    assert res.status_code == 422, res.text


@pytest.mark.asyncio
async def test_post_session_environment_unauthorized(sanic_client: SanicASGITestClient, user_headers) -> None:
    payload = {
        "name": "Environment 1",
        "description": "A session environment.",
        "container_image": "some_image:some_tag",
        "environment_image_source": "image",
    }

    _, res = await sanic_client.post("/api/data/environments", headers=user_headers, json=payload)

    assert res.status_code == 403, res.text


@pytest.mark.asyncio
async def test_patch_session_environment(
    sanic_client: SanicASGITestClient, admin_headers, create_session_environment
) -> None:
    env = await create_session_environment("Environment 1")
    environment_id = env["id"]

    command = ["python", "test.py"]
    args = ["arg1", "arg2"]
    payload = {
        "name": "New name",
        "description": "New description.",
        "container_image": "new_image:new_tag",
        "command": command,
        "args": args,
        "working_directory": "/home/user",
        "mount_directory": "/home/user/work",
    }

    _, res = await sanic_client.patch(f"/api/data/environments/{environment_id}", headers=admin_headers, json=payload)

    assert res.status_code == 200, res.text
    assert res.json is not None
    assert res.json.get("name") == "New name"
    assert res.json.get("description") == "New description."
    assert res.json.get("container_image") == "new_image:new_tag"
    assert res.json.get("args") == args
    assert res.json.get("command") == command
    assert res.json.get("working_directory") == "/home/user"
    assert res.json.get("mount_directory") == "/home/user/work"

    # Test that patching with None will reset the command and args,
    # and also that we can reset the working and mounting directories
    payload = {
        "args": None,
        "command": None,
        "working_directory": "",
        "mount_directory": "",
    }
    _, res = await sanic_client.patch(f"/api/data/environments/{environment_id}", headers=admin_headers, json=payload)
    assert res.status_code == 200, res.text
    assert res.json is not None
    assert res.json.get("args") is None
    assert res.json.get("command") is None
    assert res.json.get("working_directory") is None
    assert res.json.get("mount_directory") is None


@pytest.mark.asyncio
async def test_patch_session_environment_archived(
    sanic_client: SanicASGITestClient,
    admin_headers,
    create_session_environment,
    create_project,
    valid_resource_pool_payload,
    create_resource_pool,
) -> None:
    env = await create_session_environment("Environment 1")
    environment_id = env["id"]

    payload = {"is_archived": True}

    _, res = await sanic_client.patch(f"/api/data/environments/{environment_id}", headers=admin_headers, json=payload)

    assert res.status_code == 200, res.text
    assert res.json is not None
    assert res.json.get("is_archived")

    # Test that you can't create a launcher with an archived environment
    project = await create_project(sanic_client, "Some project")
    resource_pool_data = valid_resource_pool_payload
    resource_pool_data["public"] = False

    resource_pool = await create_resource_pool(admin=True, **resource_pool_data)

    session_payload = {
        "name": "Launcher 1",
        "project_id": project["id"],
        "description": "A session launcher.",
        "resource_class_id": resource_pool["classes"][0]["id"],
        "environment": {"id": environment_id},
    }

    _, res = await sanic_client.post("/api/data/session_launchers", headers=admin_headers, json=session_payload)

    assert res.status_code == 422, res.text

    # test unarchiving allows launcher creation again
    payload = {"is_archived": False}

    _, res = await sanic_client.patch(f"/api/data/environments/{environment_id}", headers=admin_headers, json=payload)
    assert res.status_code == 200, res.text
    assert not res.json.get("is_archived")

    _, res = await sanic_client.post("/api/data/session_launchers", headers=admin_headers, json=session_payload)

    assert res.status_code == 201, res.text


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

    assert res.status_code == 401, res.text


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
    snapshot,
) -> None:
    project_1 = await create_project(sanic_client, "Project 1")
    project_2 = await create_project(sanic_client, "Project 2")

    await create_session_launcher("Launcher 1", project_id=project_1["id"])
    await create_session_launcher("Launcher 2", project_id=project_2["id"])
    await create_session_launcher("Launcher 3", project_id=project_2["id"])

    _, res = await sanic_client.get("/api/data/session_launchers", headers=user_headers)

    assert res.status_code == 200, res.text
    assert res.json is not None
    launchers = res.json
    launchers = sorted(launchers, key=lambda e: e["name"])
    assert {launcher["name"] for launcher in launchers} == {
        "Launcher 1",
        "Launcher 2",
        "Launcher 3",
    }
    assert launchers == snapshot(exclude=props("id", "creation_date", "project_id"))


@pytest.mark.asyncio
async def test_get_session_launcher(
    sanic_client: SanicASGITestClient,
    unauthorized_headers,
    create_project,
    create_session_environment,
    create_session_launcher,
) -> None:
    project = await create_project(sanic_client, "Some project", visibility="public")
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
    project_1 = await create_project(sanic_client, "Project 1")
    project_2 = await create_project(sanic_client, "Project 2")

    await create_session_launcher("Launcher 1", project_id=project_1["id"])
    await create_session_launcher("Launcher 2", project_id=project_2["id"])
    await create_session_launcher("Launcher 3", project_id=project_2["id"])

    _, res = await sanic_client.get(f"/api/data/projects/{project_2['id']}/session_launchers", headers=user_headers)

    assert res.status_code == 200, res.text
    assert res.json is not None
    launchers = res.json
    assert {launcher["name"] for launcher in launchers} == {"Launcher 2", "Launcher 3"}


def test_env_variable_validation():
    renku_name_env_variables = {
        "RENKU_KEY_NUMBER_1": "a value",
        "RENKULAB_THING": "another value",
    }
    with pytest.raises(errors.ValidationError) as excinfo:
        EnvVar.from_dict(renku_name_env_variables)
    assert excinfo.value.message == "Env variable name 'RENKU_KEY_NUMBER_1' should not start with 'RENKU'."

    non_posix_name_env_variables = {
        "1foo": "a value",
        "thing=bar": "another value",
    }
    with pytest.raises(errors.ValidationError) as excinfo:
        EnvVar.from_dict(non_posix_name_env_variables)
    assert excinfo.value.message == "Env variable name '1foo' must match the regex '^[a-zA-Z_][a-zA-Z0-9_]*$'."


@pytest.mark.asyncio
async def test_post_session_launcher(
    sanic_client, admin_headers, create_project, create_resource_pool, app_manager
) -> None:
    project = await create_project(sanic_client, "Some project")

    resource_pool = await create_resource_pool(admin=True)

    payload = {
        "name": "Launcher 1",
        "project_id": project["id"],
        "description": "A session launcher.",
        "resource_class_id": resource_pool["classes"][0]["id"],
        "disk_storage": 2,
        "env_variables": [{"name": "KEY_NUMBER_1", "value": "a value"}],
        "environment": {
            "container_image": "some_image:some_tag",
            "name": "custom_name",
            "environment_kind": "CUSTOM",
            "environment_image_source": "image",
        },
    }

    _, res = await sanic_client.post("/api/data/session_launchers", headers=admin_headers, json=payload)

    assert res.status_code == 201, res.text
    assert res.json is not None
    assert res.json.get("name") == "Launcher 1"
    assert res.json.get("project_id") == project["id"]
    assert res.json.get("description") == "A session launcher."
    environment = res.json.get("environment", {})
    assert environment.get("name") == "custom_name"
    assert environment.get("environment_kind") == "CUSTOM"
    assert environment.get("environment_image_source") == "image"
    assert environment.get("container_image") == "some_image:some_tag"
    assert environment.get("id") is not None
    assert res.json.get("resource_class_id") == resource_pool["classes"][0]["id"]
    assert res.json.get("disk_storage") == 2
    assert res.json.get("env_variables") == [{"name": "KEY_NUMBER_1", "value": "a value"}]
    app_manager.metrics.session_launcher_created.assert_called_once()


@pytest.mark.asyncio
async def test_post_session_launcher_with_environment_build(
    sanic_client,
    admin_headers,
    create_project,
    create_resource_pool,
) -> None:
    project = await create_project(sanic_client, "Some project")

    payload = {
        "name": "Launcher 1",
        "project_id": project["id"],
        "description": "A session launcher.",
        "environment": {
            "repository": "https://github.com/some/repo",
            "builder_variant": "python",
            "frontend_variant": "vscodium",
            "environment_image_source": "build",
        },
    }

    _, response = await sanic_client.post("/api/data/session_launchers", headers=admin_headers, json=payload)

    assert response.status_code == 201, response.text
    assert response.json is not None
    assert response.json.get("name") == "Launcher 1"
    assert response.json.get("project_id") == project["id"]
    assert response.json.get("description") == "A session launcher."
    environment = response.json.get("environment", {})
    assert environment.get("id") is not None
    assert environment.get("name") == "Launcher 1"
    assert environment.get("environment_kind") == "CUSTOM"
    assert environment.get("build_parameters") == {
        "repository": "https://github.com/some/repo",
        "platforms": ["linux/amd64"],
        "builder_variant": "python",
        "frontend_variant": "vscodium",
    }
    assert environment.get("environment_image_source") == "build"
    assert environment.get("container_image") == "image:unknown-at-the-moment"


@pytest.mark.asyncio
async def test_post_session_launcher_with_advanced_environment_build(
    sanic_client: SanicASGITestClient,
    user_headers: dict[str, str],
    create_project,
) -> None:
    project = await create_project(sanic_client, "Some project")

    payload = {
        "name": "Launcher 1",
        "project_id": project["id"],
        "description": "A session launcher.",
        "environment": {
            "repository": "https://github.com/some/repo",
            "builder_variant": "python",
            "frontend_variant": "vscodium",
            "repository_revision": "some-branch",
            "context_dir": "path/to/context",
            "environment_image_source": "build",
        },
    }

    _, response = await sanic_client.post("/api/data/session_launchers", headers=user_headers, json=payload)

    assert response.status_code == 201, response.text
    assert response.json is not None
    assert response.json.get("name") == "Launcher 1"
    assert response.json.get("project_id") == project["id"]
    assert response.json.get("description") == "A session launcher."
    environment = response.json.get("environment", {})
    assert environment.get("id") is not None
    assert environment.get("name") == "Launcher 1"
    assert environment.get("environment_kind") == "CUSTOM"
    assert environment.get("build_parameters") == {
        "repository": "https://github.com/some/repo",
        "platforms": ["linux/amd64"],
        "builder_variant": "python",
        "frontend_variant": "vscodium",
        "repository_revision": "some-branch",
        "context_dir": "path/to/context",
    }
    assert environment.get("environment_image_source") == "build"
    assert environment.get("container_image") == "image:unknown-at-the-moment"


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
    project = await create_project(sanic_client, "Some project")
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
    project = await create_project(sanic_client, "Some project")
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
    project = await create_project(sanic_client, "Some project 1")
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
            "environment_image_source": "image",
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
    assert res.json.get("disk_storage") is None
    assert res.json.get("env_variables") is None

    patch_payload = {
        "name": "New Name",
        "description": "An updated session launcher.",
        "resource_class_id": resource_pool["classes"][1]["id"],
        "disk_storage": 3,
        "env_variables": [{"name": "KEY_NUMBER_2", "value": "another value"}],
    }
    _, res = await sanic_client.patch(
        f"/api/data/session_launchers/{res.json['id']}", headers=user_headers, json=patch_payload
    )
    assert res.status_code == 200, res.text
    assert res.json is not None
    assert res.json.get("name") == patch_payload["name"]
    assert res.json.get("description") == patch_payload["description"]
    assert res.json.get("resource_class_id") == patch_payload["resource_class_id"]
    assert res.json.get("disk_storage") == 3
    assert res.json.get("env_variables") == [{"name": "KEY_NUMBER_2", "value": "another value"}]


@pytest.mark.asyncio
async def test_patch_session_launcher_environment(
    sanic_client: SanicASGITestClient,
    valid_resource_pool_payload: dict[str, Any],
    user_headers,
    create_project,
    create_resource_pool,
    create_session_environment,
) -> None:
    project = await create_project(sanic_client, "Some project 1")
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
            "environment_image_source": "image",
        },
    }
    _, res = await sanic_client.post("/api/data/session_launchers", headers=user_headers, json=payload)
    assert res.status_code == 201, res.text
    assert res.json is not None
    environment = res.json.get("environment", {})
    assert environment.get("environment_kind") == "CUSTOM"
    assert environment.get("container_image") == "some_image:some_tag"
    assert environment.get("id") is not None

    launcher_id = res.json["id"]

    # Patch in a global environment
    patch_payload = {
        "environment": {"id": global_env["id"]},
    }
    _, res = await sanic_client.patch(
        f"/api/data/session_launchers/{launcher_id}", headers=user_headers, json=patch_payload
    )
    assert res.status_code == 200, res.text
    assert res.json is not None
    global_env["environment_kind"] = "GLOBAL"
    global_env["environment_image_source"] = "image"
    assert res.json["environment"] == global_env

    # Trying to patch with some random fields should fail
    patch_payload = {
        "environment": {"random_field": "random_value"},
    }
    _, res = await sanic_client.patch(
        f"/api/data/session_launchers/{launcher_id}", headers=user_headers, json=patch_payload
    )
    assert res.status_code == 422, res.text
    assert "There are errors in the following fields, id: Input should be a valid string" in res.text

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
        "environment": {
            "container_image": "new_image",
            "name": "new_custom",
            "environment_kind": "CUSTOM",
            "environment_image_source": "image",
        },
    }
    _, res = await sanic_client.patch(
        f"/api/data/session_launchers/{launcher_id}", headers=user_headers, json=patch_payload
    )
    assert res.status_code == 200, res.text

    environment_id = res.json["environment"]["id"]

    # Should be able to patch some fields of the custom environment
    patch_payload = {
        "environment": {"container_image": "nginx:latest", "args": ["a", "b", "c"]},
    }
    _, res = await sanic_client.patch(
        f"/api/data/session_launchers/{launcher_id}", headers=user_headers, json=patch_payload
    )
    assert res.status_code == 200, res.text
    assert res.json["environment"]["id"] == environment_id
    assert res.json["environment"]["container_image"] == "nginx:latest"
    assert res.json["environment"]["args"] == ["a", "b", "c"]

    # Should be able to reset args by patching in None, patching a null field should do nothing
    patch_payload = {
        "environment": {"args": None, "command": None},
    }
    _, res = await sanic_client.patch(
        f"/api/data/session_launchers/{launcher_id}", headers=user_headers, json=patch_payload
    )
    assert res.status_code == 200, res.text
    assert res.json["environment"]["id"] == environment_id
    assert res.json["environment"].get("args") is None
    assert res.json["environment"].get("command") is None

    # Should not be able to patch fields for the built environment
    patch_payload = {
        "environment": {"build_parameters": {"repository": "https://github.com/repo.get"}},
    }
    _, res = await sanic_client.patch(
        f"/api/data/session_launchers/{launcher_id}", headers=user_headers, json=patch_payload
    )
    assert res.status_code == 422, res.text

    # Should not be able to change the custom environment to be built from a repository
    patch_payload = {
        "environment": {
            "environment_image_source": "build",
            "build_parameters": {
                "repository": "https://github.com/some/repo",
                "builder_variant": "python",
                "frontend_variant": "vscodium",
            },
        },
    }

    _, res = await sanic_client.patch(
        f"/api/data/session_launchers/{launcher_id}", headers=user_headers, json=patch_payload
    )

    assert res.status_code == 200, res.text
    assert res.json is not None
    assert res.json.get("name") == "Launcher 1"
    assert res.json.get("project_id") == project["id"]
    assert res.json.get("description") == "A session launcher."
    environment = res.json.get("environment", {})
    assert environment.get("id") == environment_id
    assert environment.get("name") == "new_custom"
    assert environment.get("environment_kind") == "CUSTOM"
    assert environment.get("build_parameters") == {
        "repository": "https://github.com/some/repo",
        "platforms": ["linux/amd64"],
        "builder_variant": "python",
        "frontend_variant": "vscodium",
    }
    assert environment.get("environment_image_source") == "build"
    assert environment.get("container_image") == "image:unknown-at-the-moment"


@pytest.mark.asyncio
async def test_patch_session_launcher_environment_with_build_parameters(
    sanic_client: SanicASGITestClient,
    user_headers,
    create_project,
    create_resource_pool,
    create_session_environment,
) -> None:
    project = await create_project(sanic_client, "Some project 1")
    resource_pool = await create_resource_pool(admin=True)
    global_env = await create_session_environment("Some environment")

    # Create a global environment with the launcher
    payload = {
        "name": "Launcher 1",
        "project_id": project["id"],
        "description": "A session launcher.",
        "resource_class_id": resource_pool["classes"][0]["id"],
        "environment": {"id": global_env["id"]},
    }
    _, res = await sanic_client.post("/api/data/session_launchers", headers=user_headers, json=payload)
    assert res.status_code == 201, res.text
    assert res.json is not None
    global_env["environment_kind"] = "GLOBAL"
    global_env["environment_image_source"] = "image"
    assert res.json["environment"] == global_env

    launcher_id = res.json["id"]

    patch_payload = {
        "environment": {
            "environment_kind": "CUSTOM",
            "environment_image_source": "build",
            "build_parameters": {
                "repository": "https://github.com/some/repo",
                "builder_variant": "python",
                "frontend_variant": "vscodium",
            },
        },
    }

    _, res = await sanic_client.patch(
        f"/api/data/session_launchers/{launcher_id}", headers=user_headers, json=patch_payload
    )

    assert res.status_code == 200, res.text

    _, res = await sanic_client.get(f"/api/data/session_launchers/{launcher_id}", headers=user_headers)

    assert res.status_code == 200, res.text
    assert res.json is not None
    assert res.json.get("name") == "Launcher 1"
    assert res.json.get("project_id") == project["id"]
    assert res.json.get("description") == "A session launcher."
    environment = res.json.get("environment", {})
    assert environment.get("id") is not None
    assert environment.get("id") != global_env["id"]
    assert environment.get("name") == "Launcher 1"
    assert environment.get("environment_kind") == "CUSTOM"
    assert environment.get("build_parameters") == {
        "repository": "https://github.com/some/repo",
        "platforms": ["linux/amd64"],
        "builder_variant": "python",
        "frontend_variant": "vscodium",
    }
    assert environment.get("environment_image_source") == "build"
    assert environment.get("container_image") == "image:unknown-at-the-moment"

    environment_id = environment["id"]

    # Patch the build parameters
    patch_payload = {
        "environment": {
            "build_parameters": {
                "repository": "new_repo",
                "builder_variant": "python",
            },
        },
    }

    _, res = await sanic_client.patch(
        f"/api/data/session_launchers/{launcher_id}", headers=user_headers, json=patch_payload
    )

    assert res.status_code == 200, res.text
    assert res.json is not None
    assert res.json.get("name") == "Launcher 1"
    assert res.json.get("project_id") == project["id"]
    assert res.json.get("description") == "A session launcher."
    environment = res.json.get("environment", {})
    assert environment.get("id") == environment_id
    assert environment.get("name") == "Launcher 1"
    assert environment.get("environment_kind") == "CUSTOM"
    assert environment.get("build_parameters") == {
        "repository": "new_repo",
        "platforms": ["linux/amd64"],
        "builder_variant": "python",
        "frontend_variant": "vscodium",
    }
    assert environment.get("environment_image_source") == "build"
    assert environment.get("container_image") == "image:unknown-at-the-moment"

    # Back to a custom environment with image
    patch_payload = {
        "environment": {
            "container_image": "new_image",
            "name": "new_custom",
            "environment_kind": "CUSTOM",
            "environment_image_source": "image",
        },
    }
    _, res = await sanic_client.patch(
        f"/api/data/session_launchers/{launcher_id}", headers=user_headers, json=patch_payload
    )
    assert res.status_code == 200, res.text
    assert res.json.get("name") == "Launcher 1"
    assert res.json.get("project_id") == project["id"]
    assert res.json.get("description") == "A session launcher."
    environment = res.json.get("environment", {})
    assert environment.get("id") == environment_id
    assert environment.get("name") == "new_custom"
    assert environment.get("environment_kind") == "CUSTOM"
    assert environment.get("build_parameters") is None
    assert environment.get("environment_image_source") == "image"
    assert environment.get("container_image") == "new_image"


@pytest.mark.asyncio
@pytest.mark.parametrize("builder_variant, frontend_variant", [("conda", "vscodium"), ("python", "jupyter")])
async def test_post_session_launcher_environment_with_invalid_build_parameters(
    sanic_client, user_headers, create_project, builder_variant, frontend_variant
) -> None:
    project = await create_project(sanic_client, "Project")

    payload = {
        "name": "Launcher 1",
        "project_id": project["id"],
        "environment": {
            "repository": "https://github.com/some/repo",
            "builder_variant": builder_variant,
            "frontend_variant": frontend_variant,
            "environment_image_source": "build",
        },
    }

    _, res = await sanic_client.post("/api/data/session_launchers", headers=user_headers, json=payload)
    assert res.status_code == 422, res.text
    assert "Invalid value for the field" in res.text
    assert "Valid values are" in res.text


@pytest.mark.asyncio
@pytest.mark.parametrize("builder_variant, frontend_variant", [("conda", "vscodium"), ("python", "jupyter")])
async def test_patch_session_launcher_environment_with_invalid_build_parameters(
    sanic_client, user_headers, create_project, create_session_launcher, builder_variant, frontend_variant
) -> None:
    project = await create_project(sanic_client, "Project")

    session_launcher = await create_session_launcher(
        name="Launcher",
        project_id=project["id"],
        environment={
            "repository": "https://github.com/some/repo",
            "builder_variant": "python",
            "frontend_variant": "vscodium",
            "environment_image_source": "build",
        },
    )
    launcher_id = session_launcher["id"]

    patch_payload = {
        "environment": {
            "build_parameters": {
                "builder_variant": builder_variant,
                "frontend_variant": frontend_variant,
            },
        }
    }

    _, res = await sanic_client.patch(
        f"/api/data/session_launchers/{launcher_id}", headers=user_headers, json=patch_payload
    )
    assert res.status_code == 422, res.text
    assert "Invalid value for the field" in res.text
    assert "Valid values are" in res.text


@pytest.mark.asyncio
async def test_patch_session_launcher_invalid_env_variables(
    sanic_client: SanicASGITestClient,
    valid_resource_pool_payload: dict[str, Any],
    user_headers,
    create_project,
    create_resource_pool,
    create_session_environment,
) -> None:
    project = await create_project(sanic_client, "Some project 1")
    resource_pool_data = valid_resource_pool_payload
    resource_pool = await create_resource_pool(admin=True, **resource_pool_data)

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
            "environment_image_source": "image",
        },
    }
    _, res = await sanic_client.post("/api/data/session_launchers", headers=user_headers, json=payload)
    assert res.status_code == 201, res.text
    assert res.json is not None
    environment = res.json.get("environment", {})
    assert environment.get("environment_kind") == "CUSTOM"
    assert environment.get("container_image") == "some_image:some_tag"
    assert environment.get("id") is not None

    launcher_id = res.json["id"]
    # Should not be able use env variables that start with 'renku'
    patch_payload = {"env_variables": [{"name": "renkustuff_1", "value": "a value"}]}

    _, res = await sanic_client.patch(
        f"/api/data/session_launchers/{launcher_id}", headers=user_headers, json=patch_payload
    )
    assert res.status_code == 422, res.text
    assert "Env variable name 'renkustuff_1'" in res.text


@pytest.mark.asyncio
async def test_patch_session_launcher_reset_fields(
    sanic_client: SanicASGITestClient,
    valid_resource_pool_payload: dict[str, Any],
    user_headers,
    create_project,
    create_resource_pool,
) -> None:
    project = await create_project(sanic_client, "Some project 1")
    resource_pool_data = valid_resource_pool_payload
    resource_pool = await create_resource_pool(admin=True, **resource_pool_data)

    payload = {
        "name": "Launcher 1",
        "project_id": project["id"],
        "description": "A session launcher.",
        "resource_class_id": resource_pool["classes"][0]["id"],
        "disk_storage": 2,
        "env_variables": [{"name": "KEY_NUMBER_1", "value": "a value"}],
        "environment": {
            "container_image": "some_image:some_tag",
            "name": "custom_name",
            "environment_kind": "CUSTOM",
            "environment_image_source": "image",
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
    assert res.json.get("disk_storage") == 2
    assert res.json.get("env_variables") == [{"name": "KEY_NUMBER_1", "value": "a value"}]

    patch_payload = {"resource_class_id": None, "disk_storage": None, "env_variables": None}
    _, res = await sanic_client.patch(
        f"/api/data/session_launchers/{res.json['id']}", headers=user_headers, json=patch_payload
    )
    assert res.status_code == 200, res.text
    assert res.json is not None
    assert res.json.get("resource_class_id") is None
    assert res.json.get("disk_storage") is None
    assert res.json.get("env_variables") is None


@pytest.mark.asyncio
async def test_patch_session_launcher_keeps_unset_values(
    sanic_client, user_headers, create_project, create_resource_pool, create_session_launcher
) -> None:
    project = await create_project(sanic_client, "Some project")
    resource_pool = await create_resource_pool(admin=True)
    session_launcher = await create_session_launcher(
        name="Session Launcher",
        project_id=project["id"],
        description="A session launcher.",
        resource_class_id=resource_pool["classes"][0]["id"],
        disk_storage=42,
        env_variables=[{"name": "KEY_NUMBER_1", "value": "a value"}],
        environment={
            "container_image": "some_image:some_tag",
            "environment_kind": "CUSTOM",
            "name": "custom_name",
            "environment_image_source": "image",
        },
    )

    _, response = await sanic_client.patch(
        f"/api/data/session_launchers/{session_launcher['id']}", headers=user_headers, json={}
    )

    assert response.status_code == 200, response.text
    assert response.json is not None
    assert response.json.get("name") == "Session Launcher"
    assert response.json.get("project_id") == project["id"]
    assert response.json.get("description") == "A session launcher."
    assert response.json.get("resource_class_id") == resource_pool["classes"][0]["id"]
    assert response.json.get("disk_storage") == 42
    assert response.json.get("env_variables") == [{"name": "KEY_NUMBER_1", "value": "a value"}]
    environment = response.json.get("environment", {})
    assert environment.get("container_image") == "some_image:some_tag"
    assert environment.get("environment_kind") == "CUSTOM"
    assert environment.get("name") == "custom_name"
    assert environment.get("id") is not None


@pytest.mark.asyncio
async def test_patch_session_launcher_with_advanced_environment_build(
    sanic_client: SanicASGITestClient,
    user_headers: dict[str, str],
    create_project,
    create_resource_pool,
) -> None:
    project = await create_project(sanic_client, "Some project")

    payload = {
        "name": "Launcher 1",
        "project_id": project["id"],
        "description": "A session launcher.",
        "environment": {
            "repository": "https://github.com/some/repo",
            "builder_variant": "python",
            "frontend_variant": "vscodium",
            "environment_image_source": "build",
        },
    }

    _, res = await sanic_client.post("/api/data/session_launchers", headers=user_headers, json=payload)

    assert res.status_code == 201, res.text
    assert res.json is not None
    assert res.json.get("id") is not None
    launcher_id = res.json["id"]
    assert res.json.get("name") == "Launcher 1"
    assert res.json.get("project_id") == project["id"]
    assert res.json.get("description") == "A session launcher."
    environment = res.json.get("environment", {})
    assert environment["id"] is not None
    environment_id = environment.get("id")
    assert environment.get("name") == "Launcher 1"
    assert environment.get("environment_kind") == "CUSTOM"
    assert environment.get("build_parameters") == {
        "repository": "https://github.com/some/repo",
        "platforms": ["linux/amd64"],
        "builder_variant": "python",
        "frontend_variant": "vscodium",
    }
    assert environment.get("environment_image_source") == "build"
    assert environment.get("container_image") == "image:unknown-at-the-moment"

    patch_payload = {
        "environment": {
            "build_parameters": {
                "context_dir": "some/path",
                "repository_revision": "some-branch",
                "platforms": ["linux/arm64"],
            }
        }
    }
    _, res = await sanic_client.patch(
        f"/api/data/session_launchers/{launcher_id}", headers=user_headers, json=patch_payload
    )
    assert res.status_code == 200, res.text
    assert res.json is not None
    assert res.json.get("id") == launcher_id
    assert res.json.get("name") == "Launcher 1"
    assert res.json.get("project_id") == project["id"]
    assert res.json.get("description") == "A session launcher."
    environment = res.json.get("environment", {})
    assert environment["id"] == environment_id
    assert environment.get("name") == "Launcher 1"
    assert environment.get("environment_kind") == "CUSTOM"
    assert environment.get("build_parameters") == {
        "repository": "https://github.com/some/repo",
        "platforms": ["linux/arm64"],
        "builder_variant": "python",
        "frontend_variant": "vscodium",
        "context_dir": "some/path",
        "repository_revision": "some-branch",
    }
    assert environment.get("environment_image_source") == "build"
    assert environment.get("container_image") == "image:unknown-at-the-moment"

    # Check that we can reset the advanced parameters
    patch_payload = {
        "environment": {
            "build_parameters": {
                "context_dir": "",
            }
        }
    }
    _, res = await sanic_client.patch(
        f"/api/data/session_launchers/{launcher_id}", headers=user_headers, json=patch_payload
    )
    assert res.status_code == 200, res.text
    assert res.json is not None
    assert res.json.get("id") == launcher_id
    assert res.json.get("name") == "Launcher 1"
    assert res.json.get("project_id") == project["id"]
    assert res.json.get("description") == "A session launcher."
    environment = res.json.get("environment", {})
    assert environment["id"] == environment_id
    assert environment.get("name") == "Launcher 1"
    assert environment.get("environment_kind") == "CUSTOM"
    assert environment.get("build_parameters") == {
        "repository": "https://github.com/some/repo",
        "platforms": ["linux/arm64"],
        "builder_variant": "python",
        "frontend_variant": "vscodium",
        "repository_revision": "some-branch",
    }
    assert environment.get("environment_image_source") == "build"
    assert environment.get("container_image") == "image:unknown-at-the-moment"

    patch_payload = {
        "environment": {
            "build_parameters": {
                "frontend_variant": "jupyterlab",
                "context_dir": "",
                "repository_revision": "",
                "platforms": [],
            }
        }
    }
    _, res = await sanic_client.patch(
        f"/api/data/session_launchers/{launcher_id}", headers=user_headers, json=patch_payload
    )
    assert res.status_code == 200, res.text
    assert res.json is not None
    assert res.json.get("id") == launcher_id
    assert res.json.get("name") == "Launcher 1"
    assert res.json.get("project_id") == project["id"]
    assert res.json.get("description") == "A session launcher."
    environment = res.json.get("environment", {})
    assert environment["id"] == environment_id
    assert environment.get("name") == "Launcher 1"
    assert environment.get("environment_kind") == "CUSTOM"
    assert environment.get("build_parameters") == {
        "repository": "https://github.com/some/repo",
        "platforms": ["linux/amd64"],
        "builder_variant": "python",
        "frontend_variant": "jupyterlab",
    }
    assert environment.get("environment_image_source") == "build"
    assert environment.get("container_image") == "image:unknown-at-the-moment"


@pytest.fixture
def anonymous_user_headers() -> dict[str, str]:
    return {"Renku-Auth-Anon-Id": "some-random-value-1234"}


@pytest.mark.asyncio
@pytest.mark.skip(reason="Setup for testing sessions is not done yet.")  # TODO: enable in followup PR
async def test_starting_session_anonymous(
    sanic_client: SanicASGITestClient,
    create_project,
    create_session_launcher,
    user_headers,
    app_manager: DependencyManager,
    admin_headers,
    launch_session,
    anonymous_user_headers,
) -> None:
    _, res = await sanic_client.post(
        "/api/data/resource_pools",
        json=ResourcePool.model_validate(app_manager.default_resource_pool, from_attributes=True).model_dump(
            mode="json", exclude_none=True
        ),
        headers=admin_headers,
    )
    assert res.status_code == 201, res.text
    project: dict[str, Any] = await create_project(
        sanic_client,
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
        env_variables=[
            {"name": "TEST_ENV_VAR", "value": "some-random-value-1234"},
        ],
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


@pytest.mark.asyncio
async def test_rebuild(sanic_client: SanicASGITestClient, user_headers, create_project) -> None:
    project = await create_project(sanic_client, "Some project")
    payload = {
        "name": "Launcher 1",
        "project_id": project["id"],
        "description": "A session launcher.",
        "environment": {
            "repository": "https://github.com/some/repo",
            "builder_variant": "python",
            "frontend_variant": "vscodium",
            "environment_image_source": "build",
        },
    }
    _, response = await sanic_client.post("/api/data/session_launchers", headers=user_headers, json=payload)
    assert response.status_code == 201, response.text
    launcher = response.json
    environment_id = launcher["environment"]["id"]

    # Trying to rebuild fails since a build is already in progress when session launcher is created
    _, response = await sanic_client.post(f"/api/data/environments/{environment_id}/builds", headers=user_headers)

    assert response.status_code == 409, response.text
    assert "already has a build in progress." in response.text

    # Cancel the build
    _, response = await sanic_client.get(f"/api/data/environments/{environment_id}/builds", headers=user_headers)
    assert response.status_code == 200, response.text
    build = response.json[0]

    _, response = await sanic_client.patch(
        f"/api/data/builds/{build['id']}", json={"status": "cancelled"}, headers=user_headers
    )
    assert response.status_code == 200, response.text

    # Rebuild
    _, response = await sanic_client.post(f"/api/data/environments/{environment_id}/builds", headers=user_headers)

    assert response.status_code == 201, response.text
    assert response.json is not None
    build = response.json
    assert build.get("id") is not None
    assert build.get("environment_id") == environment_id
    assert build.get("created_at") is not None
    assert build.get("status") == "in_progress"
    assert build.get("result") is None


@pytest.mark.asyncio
async def test_get_build(sanic_client: SanicASGITestClient, user_headers, create_project) -> None:
    project = await create_project(sanic_client, "Some project")
    payload = {
        "name": "Launcher 1",
        "project_id": project["id"],
        "description": "A session launcher.",
        "environment": {
            "repository": "https://github.com/some/repo",
            "builder_variant": "python",
            "frontend_variant": "vscodium",
            "environment_image_source": "build",
        },
    }
    _, response = await sanic_client.post("/api/data/session_launchers", headers=user_headers, json=payload)
    assert response.status_code == 201, response.text
    launcher = response.json
    environment_id = launcher["environment"]["id"]

    _, response = await sanic_client.get(
        f"/api/data/environments/{environment_id}/builds",
        headers=user_headers,
    )
    assert response.status_code == 200, response.text
    build = response.json[0]
    build_id = build["id"]

    _, response = await sanic_client.get(
        f"/api/data/builds/{build_id}",
        headers=user_headers,
    )

    assert response.status_code == 200, response.text
    assert response.json is not None
    assert response.json.get("id") == build_id
    assert response.json.get("environment_id") == environment_id
    assert response.json.get("created_at") is not None
    assert response.json.get("status") == "in_progress"
    assert response.json.get("result") is None


@pytest.mark.asyncio
async def test_get_environment_builds(sanic_client: SanicASGITestClient, user_headers, create_project) -> None:
    project = await create_project(sanic_client, "Some project")
    payload = {
        "name": "Launcher 1",
        "project_id": project["id"],
        "description": "A session launcher.",
        "environment": {
            "repository": "https://github.com/some/repo",
            "builder_variant": "python",
            "frontend_variant": "vscodium",
            "environment_image_source": "build",
        },
    }
    _, response = await sanic_client.post("/api/data/session_launchers", headers=user_headers, json=payload)
    assert response.status_code == 201, response.text
    launcher = response.json
    environment_id = launcher["environment"]["id"]

    _, response = await sanic_client.get(
        f"/api/data/environments/{environment_id}/builds",
        headers=user_headers,
    )
    assert response.status_code == 200, response.text
    build1 = response.json[0]
    # Note: cancel this build so that we can post the next one
    _, response = await sanic_client.patch(
        f"/api/data/builds/{build1['id']}",
        json={"status": "cancelled"},
        headers=user_headers,
    )
    assert response.status_code == 200, response.text

    _, response = await sanic_client.post(
        f"/api/data/environments/{environment_id}/builds",
        headers=user_headers,
    )
    assert response.status_code == 201, response.text
    build2 = response.json

    _, response = await sanic_client.get(
        f"/api/data/environments/{environment_id}/builds",
        headers=user_headers,
    )

    assert response.status_code == 200, response.text
    assert response.json is not None
    builds = response.json
    assert len(builds) == 2
    assert {build.get("id") for build in builds} == {build1["id"], build2["id"]}


@pytest.mark.asyncio
async def test_patch_build(sanic_client: SanicASGITestClient, user_headers, create_project) -> None:
    project = await create_project(sanic_client, "Some project")
    payload = {
        "name": "Launcher 1",
        "project_id": project["id"],
        "description": "A session launcher.",
        "environment": {
            "repository": "https://github.com/some/repo",
            "builder_variant": "python",
            "frontend_variant": "vscodium",
            "environment_image_source": "build",
        },
    }
    _, response = await sanic_client.post("/api/data/session_launchers", headers=user_headers, json=payload)
    assert response.status_code == 201, response.text
    launcher = response.json
    environment_id = launcher["environment"]["id"]

    _, response = await sanic_client.get(
        f"/api/data/environments/{environment_id}/builds",
        headers=user_headers,
    )
    assert response.status_code == 200, response.text
    build = response.json[0]
    build_id = build["id"]

    payload = {"status": "cancelled"}

    _, response = await sanic_client.patch(
        f"/api/data/builds/{build_id}",
        json=payload,
        headers=user_headers,
    )

    assert response.status_code == 200, response.text
    assert response.json is not None
    assert response.json.get("id") == build_id
    assert response.json.get("status") == "cancelled"

    _, response = await sanic_client.get(
        f"/api/data/builds/{build_id}",
        headers=user_headers,
    )

    assert response.status_code == 200, response.text
    assert response.json is not None
    assert response.json.get("id") == build_id
    assert response.json.get("environment_id") == environment_id
    assert response.json.get("created_at") is not None
    assert response.json.get("status") == "cancelled"
    assert response.json.get("result") is None


@pytest.mark.asyncio
async def test_patch_strip_prefix(
    sanic_client: SanicASGITestClient, admin_headers, create_project, create_session_launcher
) -> None:
    project = await create_project(sanic_client, "Project 1")
    launcher = await create_session_launcher("Launcher 1", project_id=project["id"])
    launcher_id = launcher["id"]
    assert "environment" in launcher
    env = launcher["environment"]
    assert not env["strip_path_prefix"]

    payload = {
        "environment": {
            "strip_path_prefix": True,
        },
    }

    _, res = await sanic_client.patch(f"/api/data/session_launchers/{launcher_id}", headers=admin_headers, json=payload)

    assert res.status_code == 200, res.text
    assert res.json is not None
    assert "environment" in res.json
    env = res.json["environment"]
    assert env.get("strip_path_prefix")
