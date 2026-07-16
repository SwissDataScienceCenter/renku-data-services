"""Tests for sessions blueprints."""

from asyncio import AbstractEventLoop
from typing import Any

import kr8s
import pytest
from kr8s.objects import new_class
from pytest import FixtureRequest
from sanic_ext.exceptions import ValidationError
from sanic_testing.testing import SanicASGITestClient, TestingResponse
from syrupy.filters import props

from renku_data_services import errors
from renku_data_services.data_api.dependencies import DependencyManager
from renku_data_services.session.config import BuildsConfig
from renku_data_services.session.constants import BUILD_DEFAULT_OUTPUT_PRIVATE_IMAGE_PREFIX, BUILD_RUN_GVK
from renku_data_services.session.models import EnvVar
from renku_data_services.users.models import UserInfo
from test.utils import KindCluster, MemberContext

BuildRun = new_class(
    kind=BUILD_RUN_GVK.kind,
    version=BUILD_RUN_GVK.group_version,
    namespaced=True,
)


@pytest.fixture
def launch_session(
    sanic_client: SanicASGITestClient,
    user_headers: dict,
    regular_user: UserInfo,
    app_manager: DependencyManager,
    request: FixtureRequest,
    event_loop: AbstractEventLoop,
    cluster: KindCluster,
):
    async def launch_session_helper(
        payload: dict, headers: dict = None, user: UserInfo = regular_user, cookies: dict = None
    ) -> TestingResponse:
        headers = headers or user_headers
        _, res = await sanic_client.post("/api/data/sessions", headers=headers, json=payload, cookies=cookies)
        assert res.status_code == 201, res.text
        assert res.json is not None
        assert "name" in res.json
        session_id: str = res.json.get("name", "unknown")

        def cleanup():
            event_loop.run_until_complete(
                app_manager.config.nb_config.k8s_v2_client.delete_session(session_id, user.id)
            )

        request.addfinalizer(cleanup)
        return res

    return launch_session_helper


@pytest.mark.parametrize(
    "prefix,private_prefix,must_raise",
    [
        (None, None, False),  # Defaults will be used
        ("dummy/image-prefix", "dummy/private-image-prefix", False),
        (None, "dummy/private-image-prefix", False),
        ("dummy/image-prefix", None, False),
        ("dummy/private-image-prefix", "dummy/private-image-prefix", True),
        ("dummy/some-image-prefix", "dummy/some-image-prefix/suffix", True),
        ("dummy/some-image-prefix/suffix", "dummy/some-image-prefix", True),
    ],
)
def test_build_image_prefix_handling(monkeypatch, prefix, private_prefix, must_raise) -> None:
    monkeypatch.setenv("BUILD_PRIVATE_REPO_BUILDS_ENABLED", True)
    if prefix is not None:
        monkeypatch.setenv("BUILD_OUTPUT_IMAGE_PREFIX", prefix)
    if private_prefix is not None:
        monkeypatch.setenv("BUILD_OUTPUT_PRIVATE_IMAGE_PREFIX", private_prefix)

    if must_raise:
        with pytest.raises(ValidationError):
            _ = BuildsConfig.from_env()
    else:
        _ = BuildsConfig.from_env()


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
@pytest.mark.xdist_group("sessions")
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
@pytest.mark.xdist_group("sessions")
async def test_post_session_launcher(
    sanic_client,
    admin_headers,
    create_project,
    create_resource_pool,
    app_manager,
    cluster: KindCluster,
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
    assert res.json.get("launcher_type") == "interactive"
    app_manager.metrics.session_launcher_created.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.xdist_group("sessions")
async def test_post_job_launcher(
    sanic_client,
    admin_headers,
    create_project,
    create_resource_pool,
    app_manager,
    cluster: KindCluster,
) -> None:
    project = await create_project(sanic_client, "Some project")

    resource_pool = await create_resource_pool(admin=True)

    payload = {
        "name": "Launcher 2",
        "project_id": project["id"],
        "description": "A job launcher.",
        "resource_class_id": resource_pool["classes"][0]["id"],
        "disk_storage": 2,
        "env_variables": [{"name": "KEY_NUMBER_1", "value": "a value"}],
        "launcher_type": "non-interactive",
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
    assert res.json.get("name") == "Launcher 2"
    assert res.json.get("project_id") == project["id"]
    assert res.json.get("description") == "A job launcher."
    environment = res.json.get("environment", {})
    assert environment.get("name") == "custom_name"
    assert environment.get("environment_kind") == "CUSTOM"
    assert environment.get("environment_image_source") == "image"
    assert environment.get("container_image") == "some_image:some_tag"
    assert environment.get("id") is not None
    assert res.json.get("resource_class_id") == resource_pool["classes"][0]["id"]
    assert res.json.get("disk_storage") == 2
    assert res.json.get("env_variables") == [{"name": "KEY_NUMBER_1", "value": "a value"}]
    assert res.json.get("launcher_type") == "non-interactive"
    app_manager.metrics.session_launcher_created.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.xdist_group("sessions")
async def test_post_launcher_invalid_launcher_type(
    sanic_client,
    admin_headers,
    create_project,
    create_resource_pool,
    app_manager,
    cluster: KindCluster,
) -> None:
    project = await create_project(sanic_client, "Some project")

    resource_pool = await create_resource_pool(admin=True)

    payload = {
        "name": "Launcher 3",
        "project_id": project["id"],
        "description": "A launcher.",
        "resource_class_id": resource_pool["classes"][0]["id"],
        "disk_storage": 2,
        "env_variables": [{"name": "KEY_NUMBER_1", "value": "a value"}],
        "launcher_type": "blablabla",
        "environment": {
            "container_image": "some_image:some_tag",
            "name": "custom_name",
            "environment_kind": "CUSTOM",
            "environment_image_source": "image",
        },
    }

    _, res = await sanic_client.post("/api/data/session_launchers", headers=admin_headers, json=payload)

    assert res.status_code == 422, res.text


@pytest.mark.parametrize(
    "expected_status_code,git_repo,is_private",
    [
        (
            201,
            "https://github.com/SwissDataScienceCenter/renku",
            False,
        ),
        (
            201,
            "https://github.com/SwissDataScienceCenter/private",
            True,
        ),
        (500, "https://github.com/some/repo", False),
    ],
)
@pytest.mark.asyncio
@pytest.mark.xdist_group("sessions")
async def test_post_session_launcher_with_environment_build(
    app_manager: DependencyManager,
    sanic_client,
    user_headers,
    create_project,
    create_resource_pool,
    expected_status_code,
    git_repo,
    is_private,
    builds_enabled,
    cluster,
) -> None:
    project = await create_project(sanic_client, "Some project")

    payload = {
        "name": "Launcher 1",
        "project_id": project["id"],
        "description": "A session launcher.",
        "environment": {
            "repository": git_repo,
            "builder_variant": "python",
            "frontend_variant": "vscodium",
            "environment_image_source": "build",
        },
    }

    _, response = await sanic_client.post("/api/data/session_launchers", headers=user_headers, json=payload)

    if not builds_enabled:
        expected_status_code = 201

    assert response.status_code == expected_status_code, response.text
    if expected_status_code == 201:
        assert response.json is not None
        assert response.json.get("name") == "Launcher 1"
        assert response.json.get("project_id") == project["id"]
        assert response.json.get("description") == "A session launcher."
        environment = response.json.get("environment", {})
        environment_id = environment.get("id")
        assert environment_id is not None
        assert environment.get("name") == "Launcher 1"
        assert environment.get("environment_kind") == "CUSTOM"
        assert environment.get("build_parameters") == {
            "repository": git_repo,
            "platforms": ["linux/amd64"],
            "builder_variant": "python",
            "frontend_variant": "vscodium",
        }
        assert environment.get("environment_image_source") == "build"
        assert environment.get("container_image") == "image:unknown-at-the-moment"

        if builds_enabled:
            _, response = await sanic_client.get(
                f"/api/data/environments/{environment_id}/builds",
                headers=user_headers,
            )
            assert response.status_code == 200, response.text
            build = response.json[0]
            build_id = build["id"]

            api = kr8s.api(kubeconfig=cluster.kubeconfig)
            build_run = BuildRun.get(name=f"renku-{build_id.lower()}", api=api)

            build_spec = build_run.spec.build.spec
            if is_private:
                assert build_spec.source.git.get("cloneSecret") is not None
                assert build_spec.output.image.startswith(app_manager.config.builds.build_output_private_image_prefix)
                assert build_spec.output.pushSecret == app_manager.config.builds.push_private_secret_name
            else:
                assert build_spec.source.git.get("cloneSecret") is None
                assert build_spec.output.image.startswith(app_manager.config.builds.build_output_image_prefix)
                assert build_spec.output.pushSecret == app_manager.config.builds.push_secret_name

    elif expected_status_code == 500:
        assert response.json is not None
        error = response.json.get("error")
        assert error.get("message") == "no_git_repo"


@pytest.mark.parametrize(
    "expected_status_code,git_repo,is_private",
    [
        (
            201,
            "https://github.com/SwissDataScienceCenter/renku",
            False,
        ),
        (
            201,
            "https://github.com/SwissDataScienceCenter/private",
            True,
        ),
        (500, "https://github.com/some/repo", False),
    ],
)
@pytest.mark.asyncio
@pytest.mark.xdist_group("sessions")
async def test_post_job_launcher_with_environment_build(
    app_manager: DependencyManager,
    sanic_client,
    user_headers,
    create_project,
    create_resource_pool,
    expected_status_code,
    git_repo,
    is_private,
    builds_enabled,
    cluster,
) -> None:
    project = await create_project(sanic_client, "Some project")

    payload = {
        "name": "Launcher 1",
        "project_id": project["id"],
        "description": "A job launcher.",
        "launcher_type": "non-interactive",
        "environment": {
            "repository": git_repo,
            "builder_variant": "python",
            "frontend_variant": "vscodium",
            "environment_image_source": "build",
            "command": ["python"],
            "args": ["$RENKU_WORK/myscript.py"],
        },
    }

    _, response = await sanic_client.post("/api/data/session_launchers", headers=user_headers, json=payload)

    if not builds_enabled:
        expected_status_code = 201

    assert response.status_code == expected_status_code, response.text
    if expected_status_code == 201:
        assert response.json is not None
        assert response.json.get("name") == "Launcher 1"
        assert response.json.get("project_id") == project["id"]
        assert response.json.get("description") == "A job launcher."
        assert response.json.get("launcher_type") == "non-interactive"
        environment = response.json.get("environment", {})
        environment_id = environment.get("id")
        assert environment_id is not None
        assert environment.get("name") == "Launcher 1"
        assert environment.get("environment_kind") == "CUSTOM"
        assert environment.get("build_parameters") == {
            "repository": git_repo,
            "platforms": ["linux/amd64"],
            "builder_variant": "python",
            "frontend_variant": "vscodium",
        }
        assert environment.get("environment_image_source") == "build"
        assert environment.get("container_image") == "image:unknown-at-the-moment"
        assert environment.get("command") == ["python"]
        assert environment.get("args") == ["$RENKU_WORK/myscript.py"]

        if builds_enabled:
            _, response = await sanic_client.get(
                f"/api/data/environments/{environment_id}/builds",
                headers=user_headers,
            )
            assert response.status_code == 200, response.text
            build = response.json[0]
            build_id = build["id"]

            api = kr8s.api(kubeconfig=cluster.kubeconfig)
            build_run = BuildRun.get(name=f"renku-{build_id.lower()}", api=api)

            build_spec = build_run.spec.build.spec
            if is_private:
                assert build_spec.source.git.get("cloneSecret") is not None
                assert build_spec.output.image.startswith(app_manager.config.builds.build_output_private_image_prefix)
                assert build_spec.output.pushSecret == app_manager.config.builds.push_private_secret_name
            else:
                assert build_spec.source.git.get("cloneSecret") is None
                assert build_spec.output.image.startswith(app_manager.config.builds.build_output_image_prefix)
                assert build_spec.output.pushSecret == app_manager.config.builds.push_secret_name

    elif expected_status_code == 500:
        assert response.json is not None
        error = response.json.get("error")
        assert error.get("message") == "no_git_repo"


@pytest.mark.parametrize(
    "expected_status_code,git_repo,is_private",
    [
        (
            201,
            "https://github.com/SwissDataScienceCenter/renku",
            False,
        ),
        (
            201,
            "https://github.com/SwissDataScienceCenter/private",
            True,
        ),
        (500, "https://github.com/some/repo", False),
    ],
)
@pytest.mark.asyncio
@pytest.mark.xdist_group("sessions")
async def test_post_session_launcher_with_advanced_environment_build(
    app_manager: DependencyManager,
    sanic_client: SanicASGITestClient,
    user_headers: dict[str, str],
    create_project,
    expected_status_code,
    git_repo,
    is_private,
    builds_enabled,
    cluster,
) -> None:
    project = await create_project(sanic_client, "Some project")

    payload = {
        "name": "Launcher 1",
        "project_id": project["id"],
        "description": "A session launcher.",
        "environment": {
            "repository": git_repo,
            "builder_variant": "python",
            "frontend_variant": "vscodium",
            "repository_revision": "some-branch",
            "context_dir": "path/to/context",
            "environment_image_source": "build",
        },
    }

    _, response = await sanic_client.post("/api/data/session_launchers", headers=user_headers, json=payload)

    if not builds_enabled:
        expected_status_code = 201

    assert response.status_code == expected_status_code, response.text
    if expected_status_code == 201:
        assert response.json is not None
        assert response.json.get("name") == "Launcher 1"
        assert response.json.get("project_id") == project["id"]
        assert response.json.get("description") == "A session launcher."
        environment = response.json.get("environment", {})
        environment_id = environment.get("id")
        assert environment_id is not None
        assert environment.get("name") == "Launcher 1"
        assert environment.get("environment_kind") == "CUSTOM"
        assert environment.get("build_parameters") == {
            "repository": git_repo,
            "platforms": ["linux/amd64"],
            "builder_variant": "python",
            "frontend_variant": "vscodium",
            "repository_revision": "some-branch",
            "context_dir": "path/to/context",
        }
        assert environment.get("environment_image_source") == "build"
        assert environment.get("container_image") == "image:unknown-at-the-moment"

        if builds_enabled:
            _, response = await sanic_client.get(
                f"/api/data/environments/{environment_id}/builds",
                headers=user_headers,
            )
            assert response.status_code == 200, response.text
            build = response.json[0]
            build_id = build["id"]

            api = kr8s.api(kubeconfig=cluster.kubeconfig)
            build_run = BuildRun.get(name=f"renku-{build_id.lower()}", api=api)

            build_spec = build_run.spec.build.spec
            if is_private:
                assert build_spec.source.git.get("cloneSecret") is not None
                assert build_spec.output.image.startswith(app_manager.config.builds.build_output_private_image_prefix)
                assert build_spec.output.pushSecret == app_manager.config.builds.push_private_secret_name
            else:
                assert build_spec.source.git.get("cloneSecret") is None
                assert build_spec.output.image.startswith(app_manager.config.builds.build_output_image_prefix)
                assert build_spec.output.pushSecret == app_manager.config.builds.push_secret_name

    elif expected_status_code == 500:
        assert response.json is not None
        error = response.json.get("error")
        assert error.get("message") == "no_git_repo"


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
@pytest.mark.xdist_group("sessions")  # Needs to run on the same worker as the rest of the sessions tests
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
    assert "There are errors in the following fields" in res.text

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
@pytest.mark.xdist_group("sessions")  # Needs to run on the same worker as the rest of the sessions tests
async def test_patch_session_launcher_from_code_update_command(
    sanic_client: SanicASGITestClient,
    user_headers,
    create_project,
    create_resource_pool,
    create_session_environment,
) -> None:
    project = await create_project(sanic_client, "Some project 1")
    resource_pool = await create_resource_pool(admin=True)

    # create initial session launcher as a build-from-code
    payload = {
        "project_id": project["id"],
        "resource_class_id": resource_pool["id"],
        "name": "Test name from code",
        "launcher_type": "non-interactive",
        "environment": {
            "environment_image_source": "build",
            "builder_variant": "python",
            "frontend_variant": "jupyterlab",
            "repository": "https://github.com/eikek/bfc_test",
            "platforms": ["linux/amd64"],
            "command": ["python", "dummy.py"],
        },
    }
    _, res = await sanic_client.post("/api/data/session_launchers", headers=user_headers, json=payload)
    assert res.status_code == 201, res.text
    assert res.json is not None
    assert res.json["environment"]["environment_kind"] == "CUSTOM"

    launcher_id = res.json["id"]

    patch_payload = {
        "environment": {"environment_kind": "CUSTOM", "build_parameters": {}, "command": ["python", "dummy2.sh"]}
    }
    _, res = await sanic_client.patch(
        f"/api/data/session_launchers/{launcher_id}", headers=user_headers, json=patch_payload
    )

    assert res.status_code == 200, res.text
    assert res.json is not None
    assert res.json["environment"]["command"] == ["python", "dummy2.sh"]
    assert res.json["launcher_type"] == "non-interactive"

    _, res = await sanic_client.get(f"/api/data/session_launchers/{launcher_id}", headers=user_headers)

    assert res.status_code == 200, res.text
    assert res.json is not None
    assert res.json["environment"]["command"] == ["python", "dummy2.sh"]
    assert res.json["launcher_type"] == "non-interactive"


@pytest.mark.asyncio
@pytest.mark.xdist_group("sessions")  # Needs to run on the same worker as the rest of the sessions tests
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
    sanic_client,
    user_headers,
    create_project,
    builder_variant,
    frontend_variant,
) -> None:
    project = await create_project(sanic_client, "Project")

    payload = {
        "name": "Launcher 1",
        "project_id": project["id"],
        "environment": {
            "repository": "https://github.com/SwissDataScienceCenter/renku",
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
            "repository": "https://github.com/SwissDataScienceCenter/renku",
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
@pytest.mark.xdist_group("sessions")  # Needs to run on the same worker as the rest of the sessions tests
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
    sanic_client,
    user_headers,
    create_project,
    create_resource_pool,
    create_session_launcher,
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
@pytest.mark.xdist_group("sessions")  # Needs to run on the same worker as the rest of the sessions tests
async def test_patch_session_launcher_with_advanced_environment_build(
    sanic_client: SanicASGITestClient,
    user_headers: dict[str, str],
    create_project,
    create_resource_pool,
) -> None:
    project = await create_project(sanic_client, "Some project")

    repository = "https://github.com/SwissDataScienceCenter/renku"
    payload = {
        "name": "Launcher 1",
        "project_id": project["id"],
        "description": "A session launcher.",
        "environment": {
            "repository": repository,
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
        "repository": repository,
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
        "repository": repository,
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
        "repository": repository,
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
        "repository": repository,
        "platforms": ["linux/amd64"],
        "builder_variant": "python",
        "frontend_variant": "jupyterlab",
    }
    assert environment.get("environment_image_source") == "build"
    assert environment.get("container_image") == "image:unknown-at-the-moment"


@pytest.fixture
def anonymous_user_headers() -> dict[str, str]:
    return {"Renku-Auth-Anon-Id": "some-random-value-1234"}


def id_from_launcher(val: Any) -> str | None:
    if isinstance(val, dict):
        return val["name"].replace(" ", "-")
    return ""


@pytest.fixture
def actual_user_headers(request, regular_user_access_token) -> dict[str, str]:
    if request.param == "anonymous":
        return {"Renku-Auth-Anon-Id": "some-random-value-1234"}
    else:
        return {"Authorization": f"Bearer {regular_user_access_token}"}


@pytest.mark.asyncio
@pytest.mark.xdist_group("sessions")  # Needs to run on the same worker as the rest of the sessions tests
@pytest.mark.parametrize(
    "actual_user_headers",
    ["anonymous", "user"],
    indirect=True,
)
@pytest.mark.parametrize(
    "builds_config",
    [
        pytest.param(
            {"enabled": True, "build_output_private_image_prefix": BUILD_DEFAULT_OUTPUT_PRIVATE_IMAGE_PREFIX},
            id="enabled",
        ),
        pytest.param({"enabled": False, "build_output_private_image_prefix": None}, id="disabled"),
    ],
)
@pytest.mark.parametrize(
    "launcher_conf,expected_status_code,expected_error_message",
    [
        (
            {
                "name": "Valid custom image",
                "description": "A session launcher",
                "environment": {
                    "container_image": "renku/renkulab-py:3.10-0.23.0-amalthea-sessions-3",
                    "environment_kind": "CUSTOM",
                    "name": "test",
                    "port": 8888,
                    "environment_image_source": "image",
                },
            },
            201,
            None,
        ),
    ],
    ids=id_from_launcher,
)
async def test_starting_session(
    app_manager: DependencyManager,
    sanic_client: SanicASGITestClient,
    admin_headers,
    create_project,
    create_resource_pool,
    create_session_launcher,
    launch_session,
    amalthea_installation,
    actual_user_headers,
    launcher_conf,
    expected_status_code,
    expected_error_message,
    builds_config,
) -> None:
    project: dict[str, Any] = await create_project(
        sanic_client,
        "Some project",
        visibility="public",
        repositories=["https://github.com/SwissDataScienceCenter/renku-data-services"],
    )
    resource_pool = await create_resource_pool(admin=True)

    launcher_conf.update(
        dict(
            project_id=project["id"],
            resource_class_id=resource_pool["classes"][0]["id"],
            disk_storage=42,
        )
    )

    if not builds_config["enabled"]:
        expected_status_code = 201

    with MemberContext(app_manager.config.builds, builds_config):
        launcher: dict[str, Any] = await create_session_launcher(**launcher_conf)

        launcher_id = launcher["id"]
        project_id = project["id"]
        payload = {"project_id": project_id, "launcher_id": launcher_id}
        cookies = {"_renku_session": "some content"}

        _, session_res = await sanic_client.post(
            "/api/data/sessions", headers=actual_user_headers, json=payload, cookies=cookies
        )
        assert session_res.status_code == expected_status_code

        if expected_status_code == 201:
            _, res = await sanic_client.get(
                f"/api/data/sessions/{session_res.json['name']}", headers=actual_user_headers, cookies=cookies
            )
            assert res.status_code == 200, res.text
            assert res.json["name"] == session_res.json["name"]
            _, res = await sanic_client.get("/api/data/sessions", headers=actual_user_headers, cookies=cookies)
            assert res.status_code == 200, res.text
            assert len(res.json) > 0
            assert session_res.json["name"] in [i["name"] for i in res.json]
        else:
            assert session_res.json["error"]["message"] == expected_error_message


@pytest.mark.asyncio
@pytest.mark.xdist_group("sessions")  # Needs to run on the same worker as the rest of the sessions tests
@pytest.mark.parametrize(
    "actual_user_headers",
    ["anonymous", "user"],
    indirect=True,
)
@pytest.mark.parametrize(
    "launcher_conf,repositories,expected_status_code,expected_error_message",
    [
        (
            {
                "name": "Valid custom image",
                "description": "A session launcher",
                "environment": {
                    "container_image": "renku/renkulab-py:3.10-0.23.0-amalthea-sessions-3",
                    "environment_kind": "CUSTOM",
                    "name": "test",
                    "port": 8888,
                    "environment_image_source": "image",
                },
            },
            ["https://github.com/SwissDataScienceCenter/renku-data-services"],
            201,
            None,
        ),
        (
            {
                "name": "Private build image with accessible repository",
                "description": "A session launcher",
                "environment": {
                    "environment_image_source": "build",
                    "repository": "https://github.com/SwissDataScienceCenter/private",
                    "builder_variant": "python",
                    "frontend_variant": "vscodium",
                },
            },
            ["https://github.com/SwissDataScienceCenter/private"],
            201,
            None,
        ),
        (
            {
                "name": "Private build image with inaccessible repository",
                "description": "A session launcher",
                "environment": {
                    "environment_image_source": "build",
                    "repository": "https://github.com/SwissDataScienceCenter/other-private",
                    "builder_variant": "python",
                    "frontend_variant": "vscodium",
                },
            },
            ["https://github.com/SwissDataScienceCenter/other-private"],
            201,
            None,
        ),
        (
            {
                "name": "Private build image with a repository not in the list",
                "description": "A session launcher",
                "environment": {
                    "environment_image_source": "build",
                    "repository": "https://github.com/SwissDataScienceCenter/renku",
                    "builder_variant": "python",
                    "frontend_variant": "vscodium",
                },
            },
            ["https://github.com/SwissDataScienceCenter/private"],
            201,
            None,
        ),
    ],
    ids=id_from_launcher,
)
@pytest.mark.skipif(
    "not config.getoption('--enable-builds')",
    reason="Only run when --enable-builds is given",
)
async def test_starting_session_with_builds_enabled(
    app_manager: DependencyManager,
    sanic_client: SanicASGITestClient,
    admin_headers,
    create_project,
    create_resource_pool,
    create_session_launcher,
    launch_session,
    amalthea_installation,
    launcher_conf,
    expected_status_code,
    expected_error_message,
    repositories,
    actual_user_headers,
) -> None:
    project: dict[str, Any] = await create_project(
        sanic_client,
        "Some project",
        visibility="public",
        repositories=repositories,
    )
    resource_pool = await create_resource_pool(admin=True)

    launcher_conf.update(
        dict(
            project_id=project["id"],
            resource_class_id=resource_pool["classes"][0]["id"],
            disk_storage=42,
        )
    )

    app_manager.config.builds.enabled = True  # This is the default for testing but ensures
    launcher: dict[str, Any] = await create_session_launcher(**launcher_conf)

    launcher_id = launcher["id"]
    project_id = project["id"]
    payload = {"project_id": project_id, "launcher_id": launcher_id}
    cookies = {"_renku_session": "some content"}

    _, session_res = await sanic_client.post(
        "/api/data/sessions", headers=actual_user_headers, json=payload, cookies=cookies
    )
    assert session_res.status_code == expected_status_code

    if expected_status_code == 201:
        _, res = await sanic_client.get(
            f"/api/data/sessions/{session_res.json['name']}", headers=actual_user_headers, cookies=cookies
        )
        assert res.status_code == 200, res.text
        assert res.json["name"] == session_res.json["name"]
        _, res = await sanic_client.get("/api/data/sessions", headers=actual_user_headers, cookies=cookies)
        assert res.status_code == 200, res.text
        assert len(res.json) > 0
        assert session_res.json["name"] in [i["name"] for i in res.json]
    else:
        assert session_res.json["error"]["message"] == expected_error_message


@pytest.mark.skipif(
    "not config.getoption('--enable-builds')",
    reason="Only run when --enable-builds is given",
)
async def test_creating_session_launcher_with_builds_enabled_but_private_builds_disabled(
    app_manager: DependencyManager,
    sanic_client: SanicASGITestClient,
    create_project,
    create_resource_pool,
    create_session_launcher,
    user_headers,
) -> None:
    project: dict[str, Any] = await create_project(
        sanic_client,
        "Some project",
        visibility="public",
        repositories=["https://github.com/SwissDataScienceCenter/private"],
    )
    resource_pool = await create_resource_pool(admin=True)

    launcher_conf = {
        "project_id": project["id"],
        "resource_class_id": resource_pool["classes"][0]["id"],
        "disk_storage": 42,
        "name": "Private build image with accessible repository",
        "description": "A session launcher",
        "environment": {
            "environment_image_source": "build",
            "repository": "https://github.com/SwissDataScienceCenter/private",
            "builder_variant": "python",
            "frontend_variant": "vscodium",
        },
    }

    builds_config = {"enabled": True, "private_builds_enabled": False}

    with MemberContext(app_manager.config.builds, builds_config):
        _, res = await sanic_client.post("/api/data/session_launchers", headers=user_headers, json=launcher_conf)
        assert res.status_code == 500
        assert res.json["error"]["message"] == "Private repository builds are not enabled"


@pytest.mark.parametrize(
    "expected_status_code,build_git_repo,request_git_repo, is_private",
    [
        (
            201,
            "https://github.com/SwissDataScienceCenter/renku",
            "https://github.com/SwissDataScienceCenter/renku",
            False,
        ),
        (
            201,
            "https://github.com/SwissDataScienceCenter/private",
            "https://github.com/SwissDataScienceCenter/private",
            True,
        ),
        (
            201,
            "https://github.com/SwissDataScienceCenter/renku",
            "https://github.com/SwissDataScienceCenter/not-the same",
            False,
        ),
        (
            201,
            "https://github.com/SwissDataScienceCenter/other-private",
            "https://github.com/SwissDataScienceCenter/other-private",
            True,
        ),
    ],
)
@pytest.mark.asyncio
@pytest.mark.xdist_group("sessions")  # Needs to run on the same worker as the rest of the sessions tests
async def test_starting_session_with_built_environment(
    sanic_client: SanicASGITestClient,
    create_project,
    create_resource_pool,
    create_session_launcher,
    user_headers,
    app_manager: DependencyManager,
    admin_headers,
    launch_session,
    expected_status_code,
    build_git_repo,
    request_git_repo,
    is_private,
    builds_enabled,
) -> None:
    project: dict[str, Any] = await create_project(
        sanic_client,
        "Some project",
        visibility="public",
        repositories=[request_git_repo],
    )
    resource_pool = await create_resource_pool(admin=True)
    launcher: dict[str, Any] = await create_session_launcher(
        name="Launcher 1",
        project_id=project["id"],
        description="A session launcher",
        resource_class_id=resource_pool["classes"][0]["id"],
        environment={
            "repository": build_git_repo,
            "builder_variant": "python",
            "frontend_variant": "vscodium",
            "environment_image_source": "build",
        },
        env_variables=[
            {"name": "TEST_ENV_VAR", "value": "some-random-value-1234"},
        ],
    )

    launcher_id = launcher["id"]
    project_id = project["id"]
    payload = {"project_id": project_id, "launcher_id": launcher_id}

    _, session_res = await sanic_client.post("/api/data/sessions", headers=user_headers, json=payload)
    assert session_res.status_code == expected_status_code

    if expected_status_code == 201:
        _, res = await sanic_client.get(f"/api/data/sessions/{session_res.json['name']}", headers=user_headers)
        assert res.status_code == 200, res.text
        assert res.json["name"] == session_res.json["name"]
        _, res = await sanic_client.get("/api/data/sessions", headers=user_headers)
        assert res.status_code == 200, res.text
        assert len(res.json) > 0
        assert session_res.json["name"] in [i["name"] for i in res.json]


@pytest.mark.asyncio
async def test_rebuild(
    sanic_client: SanicASGITestClient,
    user_headers,
    create_project,
    builds_enabled,
) -> None:
    project = await create_project(sanic_client, "Some project")
    payload = {
        "name": "Launcher 1",
        "project_id": project["id"],
        "description": "A session launcher.",
        "environment": {
            "repository": "https://github.com/SwissDataScienceCenter/renku",
            "builder_variant": "python",
            "frontend_variant": "vscodium",
            "environment_image_source": "build",
        },
    }
    _, response = await sanic_client.post("/api/data/session_launchers", headers=user_headers, json=payload)
    assert response.status_code == 201, response.text
    launcher = response.json
    environment_id = launcher["environment"]["id"]

    if not builds_enabled:
        # If builds are enabled, the build will have failed due to the inaccessibility of the registry hence it can
        # directly be restarted
        # Trying to rebuild fails since a build is already in progress when session launcher is created
        _, response = await sanic_client.post(f"/api/data/environments/{environment_id}/builds", headers=user_headers)

        assert response.status_code == 409, response.text
        assert "already has a build in progress." in response.text

    # Cancel the build
    _, response = await sanic_client.get(f"/api/data/environments/{environment_id}/builds", headers=user_headers)
    assert response.status_code == 200, response.text
    build = response.json[0]

    _, response = await sanic_client.get(f"/api/data/builds/{build['id']}", headers=user_headers)
    assert response.status_code == 200, response.text

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
    if not builds_enabled:
        assert build.get("status") == "in_progress"
    else:
        assert build.get("status") in ["failed", "in_progress"]
    assert build.get("result") is None


@pytest.mark.asyncio
async def test_get_build(
    sanic_client: SanicASGITestClient,
    user_headers,
    create_project,
) -> None:
    project = await create_project(sanic_client, "Some project")
    payload = {
        "name": "Launcher 1",
        "project_id": project["id"],
        "description": "A session launcher.",
        "environment": {
            "repository": "https://github.com/SwissDataScienceCenter/renku",
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
async def test_get_environment_builds(
    sanic_client: SanicASGITestClient,
    user_headers,
    create_project,
) -> None:
    project = await create_project(sanic_client, "Some project")
    payload = {
        "name": "Launcher 1",
        "project_id": project["id"],
        "description": "A session launcher.",
        "environment": {
            "repository": "https://github.com/SwissDataScienceCenter/renku",
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
async def test_patch_build(
    sanic_client: SanicASGITestClient,
    user_headers,
    create_project,
) -> None:
    project = await create_project(sanic_client, "Some project")
    payload = {
        "name": "Launcher 1",
        "project_id": project["id"],
        "description": "A session launcher.",
        "environment": {
            "repository": "https://github.com/SwissDataScienceCenter/renku",
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
    sanic_client: SanicASGITestClient,
    admin_headers,
    create_project,
    create_session_launcher,
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
