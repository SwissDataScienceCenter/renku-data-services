"""Tests for notebook blueprints."""

import asyncio
from collections.abc import AsyncIterator, Generator
from contextlib import suppress
from datetime import datetime
from pathlib import PurePosixPath
from uuid import uuid4

import pytest
import pytest_asyncio
from kr8s import NotFoundError
from sanic_testing.testing import SanicASGITestClient
from ulid import ULID

from renku_data_services.base_models import AnonymousAPIUser
from renku_data_services.base_models.core import APIUser
from renku_data_services.data_api.dependencies import DependencyManager
from renku_data_services.notebooks.core_sessions import get_mount_work_dir
from renku_data_services.notebooks.crs import (
    AmaltheaSessionSpec,
    AmaltheaSessionV1Alpha1,
    Resources,
    Session,
    Type,
)
from renku_data_services.session.models import Environment, EnvironmentImageSource, EnvironmentKind, Member


@pytest.fixture
def non_mocked_hosts() -> list:
    """Hosts that should not get mocked during tests."""

    return ["127.0.0.1"]


@pytest.fixture
def renku_image() -> str:
    return "ghcr.io/swissdatasciencecenter/renku/py-basic-vscodium:2.9.0"


@pytest.fixture
def unknown_server_name() -> str:
    return "unknown"


@pytest.fixture
def server_name() -> str:
    random_name_part = str(uuid4())
    session_name = f"test-session-{random_name_part}"
    return session_name


@pytest.fixture
def pod_name(server_name: str) -> str:
    return f"{server_name}-0"


@pytest_asyncio.fixture()
async def amalthea_session(
    renku_image: str,
    server_name: str,
    notebooks_fixtures,
    app_manager_instance: DependencyManager,
    regular_user_api_user: APIUser,
    create_resource_pool,
    create_project,
    create_session_launcher,
    sanic_client,
) -> AsyncIterator[AmaltheaSessionV1Alpha1]:
    """Fake server for non pod related tests"""

    rp = await create_resource_pool(admin=True)
    assert "classes" in rp
    assert len(rp["classes"]) >= 2
    rc = rp["classes"][0]
    proj = await create_project(sanic_client, "proj1")
    env = {
        "environment_kind": "CUSTOM",
        "name": "Test",
        "container_image": renku_image,
        "environment_image_source": "image",
    }
    launcher = await create_session_launcher("launcher_name", proj["id"], **{"environment": env})
    session = AmaltheaSessionV1Alpha1(
        metadata=dict(
            name=server_name,
            labels={
                "renku.io/safe-username": regular_user_api_user.id,
                "renku.io/userId": regular_user_api_user.id,
                "renku.io/session-type": "interactive",
            },
            annotations={
                "renku.io/resource_class_id": str(rc["id"]),
                "renku.io/project_id": proj["id"],
                "renku.io/launcher_id": launcher["id"],
            },
        ),
        spec=AmaltheaSessionSpec(
            session=Session(
                image=renku_image,
                resources=Resources(
                    requests={
                        "cpu": "100m",
                        "memory": "1Gi",
                    }
                ),
            ),
            hibernated=False,
        ),
    )
    yield await app_manager_instance.config.nb_config.k8s_v2_client.create_session(session, regular_user_api_user)

    # NOTE: This is used also in tests that check if the server was properly stopped
    # in this case the server will already be gone when we try to delete it in the cleanup here.
    with suppress(NotFoundError):
        await app_manager_instance.config.nb_config.k8s_v2_client.delete_session(server_name, regular_user_api_user.id)


@pytest.fixture()
def authenticated_user_headers(user_headers):
    return dict({"Renku-Auth-Refresh-Token": "test-refresh-token"}, **user_headers)


class AttributeDictionary(dict):
    """Enables accessing dictionary keys as attributes"""

    def __init__(self, dictionary):
        super().__init__()
        for key, value in dictionary.items():
            # TODO check if key is a valid identifier
            if key == "list":
                raise ValueError("'list' is not allowed as a key")
            if isinstance(value, dict):
                value = AttributeDictionary(value)
            elif isinstance(value, list):
                value = [AttributeDictionary(v) if isinstance(v, dict) else v for v in value]
            self.__setattr__(key, value)
            self[key] = value

    def list(self):
        return [value for _, value in self.items()]

    def __setitem__(self, k, v):
        if k == "list":
            raise ValueError("'list' is not allowed as a key")
        self.__setattr__(k, v)
        return super().__setitem__(k, v)


async def wait_for(sanic_client: SanicASGITestClient, user_headers, server_name: str, max_timeout: int = 60):
    res = None
    waited = 0
    for t in list(range(0, max_timeout)):
        waited = t + 1
        _, res = await sanic_client.get(f"/api/data/sessions/{server_name}", headers=user_headers)
        if res.status_code == 200:
            return
        await asyncio.sleep(1)  # wait a bit for k8s events to be processed in the background

    raise Exception(
        f"Timeout reached while waiting for {server_name} to be ready."
        f" res {res.json if res is not None else None}, waited {waited} seconds"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("image,exists", [("python:3.12", True), ("shouldnotexist:0.42", False)])
async def test_check_docker_image(sanic_client: SanicASGITestClient, user_headers, image, exists):
    """Validate that the images endpoint answers correctly.

    Needs the responses package in case docker queries must be mocked
    """

    _, res = await sanic_client.get(f"/api/data/sessions/images/?image_url={image}", headers=user_headers)

    assert res.status_code == 200, res.text
    assert res.json["accessible"] == exists


@pytest.fixture
def notebooks_fixtures(cluster, amalthea_installation, amalthea_session_k8s_watcher) -> Generator[None, None]:
    yield


@pytest.mark.xdist_group("sessions")  # Needs to run on the same worker as the rest of the sessions tests
@pytest.mark.sessions
@pytest.mark.asyncio
async def test_user_server_list(
    sanic_client: SanicASGITestClient,
    authenticated_user_headers,
    amalthea_session: AmaltheaSessionV1Alpha1,
    notebooks_fixtures,
):
    """Validate that the user server list endpoint answers correctly"""

    await asyncio.sleep(1)  # wait a bit for k8s events to be processed in the background

    _, res = await sanic_client.get("/api/data/sessions", headers=authenticated_user_headers)

    assert res.status_code == 200, res.text
    assert len(res.json) == 1
    assert res.json[0]["name"] == amalthea_session.metadata.name
    assert res.json[0]["session_type"] == "interactive"


@pytest.mark.xdist_group("sessions")  # Needs to run on the same worker as the rest of the sessions tests
@pytest.mark.sessions
@pytest.mark.asyncio
@pytest.mark.parametrize("server_exists,expected_status_code", [(False, 404), (True, 200)])
async def test_log_retrieval(
    sanic_client: SanicASGITestClient,
    server_exists,
    expected_status_code,
    authenticated_user_headers,
    notebooks_fixtures,
    amalthea_session: AmaltheaSessionV1Alpha1,
):
    """Validate that the logs endpoint answers correctly"""

    server_name = "unknown_server"
    if server_exists:
        server_name = amalthea_session.metadata.name
        await wait_for(sanic_client, authenticated_user_headers, server_name)

    _, res = await sanic_client.get(f"/api/data/sessions/{server_name}/logs", headers=authenticated_user_headers)

    assert res.status_code == expected_status_code, res.text


@pytest.mark.xdist_group("sessions")  # Needs to run on the same worker as the rest of the sessions tests
@pytest.mark.sessions
@pytest.mark.asyncio
@pytest.mark.parametrize("server_exists,expected_status_code", [(False, 204), (True, 204)])
async def test_stop_server(
    sanic_client: SanicASGITestClient,
    server_exists,
    amalthea_session: AmaltheaSessionV1Alpha1,
    expected_status_code,
    authenticated_user_headers,
    notebooks_fixtures,
):
    server_name = "unknown_server"
    if server_exists:
        server_name = amalthea_session.metadata.name

    _, res = await sanic_client.delete(f"/api/data/sessions/{server_name}", headers=authenticated_user_headers)

    assert res.status_code == expected_status_code, res.text


@pytest.mark.xdist_group("sessions")  # Needs to run on the same worker as the rest of the sessions tests
@pytest.mark.sessions
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "server_exists,expected_status_code, patch",
    [(False, 404, {}), (True, 200, {"state": "hibernated"}), (True, 200, {"resource_class_id": 2})],
)
async def test_patch_server(
    sanic_client: SanicASGITestClient,
    server_exists,
    amalthea_session: AmaltheaSessionV1Alpha1,
    expected_status_code,
    patch,
    authenticated_user_headers,
    notebooks_fixtures,
):
    server_name = "unknown_server"
    if server_exists:
        server_name = amalthea_session.metadata.name
        await wait_for(sanic_client, authenticated_user_headers, server_name)

    _, res = await sanic_client.patch(
        f"/api/data/sessions/{server_name}", json=patch, headers=authenticated_user_headers
    )

    assert res.status_code == expected_status_code, res.text
    if expected_status_code == 200 and patch == {"state": "hibernated"}:
        # NOTE: The status of amalthea needs a few seconds to update and show up in the response
        await asyncio.sleep(2)
        _, res = await sanic_client.get(f"/api/data/sessions/{server_name}", headers=authenticated_user_headers)
        assert res.status_code == 200
        assert res.json["status"]["state"] == "hibernated"
    if expected_status_code == 200 and "resource_class_id" in patch:
        assert res.json["resource_class_id"] == patch["resource_class_id"]


@pytest.mark.xdist_group("sessions")  # Needs to run on the same worker as the rest of the sessions tests
@pytest.mark.sessions
@pytest.mark.asyncio
async def test_start_server(
    sanic_client: SanicASGITestClient,
    authenticated_user_headers,
    notebooks_fixtures,
    create_session_launcher,
    create_project,
    renku_image,
    create_resource_pool,
    app_manager_instance: DependencyManager,
):
    proj = await create_project(sanic_client, "proj1")
    env = {
        "environment_kind": "CUSTOM",
        "name": "Test",
        "container_image": renku_image,
        "environment_image_source": "image",
    }
    launcher = await create_session_launcher("launcher_name", proj["id"], **{"environment": env})
    data = {"launcher_id": launcher["id"], "resource_class_id": 1}
    _ = await create_resource_pool(admin=True)
    cookies = {app_manager_instance.config.nb_config.session_id_cookie_name: "session_id"}

    _, res = await sanic_client.post(
        "/api/data/sessions/", json=data, headers=authenticated_user_headers, cookies=cookies
    )

    assert res.status_code == 201, res.text

    server_name: str = res.json["name"]
    _, res = await sanic_client.delete(f"/api/data/sessions/{server_name}", headers=authenticated_user_headers)

    assert res.status_code == 204, res.text


@pytest.mark.xdist_group("sessions")  # Needs to run on the same worker as the rest of the sessions tests
@pytest.mark.sessions
@pytest.mark.asyncio
async def test_not_found_server(
    sanic_client: SanicASGITestClient,
    authenticated_user_headers: dict[str, str],
    notebooks_fixtures,
):
    server_name = "unknown_server"

    _, res = await sanic_client.get(f"/api/data/sessions/{server_name}", headers=authenticated_user_headers)

    assert res.status_code == 404, res.text


@pytest.mark.xdist_group("sessions")  # Needs to run on the same worker as the rest of the sessions tests
@pytest.mark.sessions
@pytest.mark.asyncio
async def test_start_server_remote_readiness_probe(
    sanic_client: SanicASGITestClient,
    authenticated_user_headers,
    notebooks_fixtures,
    create_session_launcher,
    create_project,
    renku_image,
    create_resource_pool,
    app_manager_instance: DependencyManager,
    regular_user_api_user: APIUser,
    admin_headers: dict[str, str],
):
    """Remote interactive sessions should use an HTTP readiness probe."""
    # Create an OAuth2 provider required for a remote resource pool.
    provider_payload = {
        "id": "test-provider-for-remote-session-notebooks",
        "kind": "gitlab",
        "client_id": "test-client-id",
        "display_name": "Test Provider",
        "scope": "api",
        "url": "https://example.org",
    }
    _, res = await sanic_client.post("/api/data/oauth2/providers", headers=admin_headers, json=provider_payload)
    assert res.status_code == 201, res.text

    # Create a private resource pool and patch it to be remote.
    rp = await create_resource_pool(admin=True, public=False)
    patch = {
        "remote": {
            "kind": "firecrest",
            "provider_id": provider_payload["id"],
            "api_url": "https://example.org",
            "system_name": "my-system",
        },
    }
    _, res = await sanic_client.patch(f"/api/data/resource_pools/{rp['id']}", headers=admin_headers, json=patch)
    assert res.status_code == 200, res.text

    proj = await create_project(sanic_client, "proj1")
    env = {
        "environment_kind": "CUSTOM",
        "name": "Test",
        "container_image": renku_image,
        "environment_image_source": "image",
    }
    launcher = await create_session_launcher("launcher_name", proj["id"], **{"environment": env})
    data = {"launcher_id": launcher["id"], "resource_class_id": rp["classes"][0]["id"]}
    cookies = {app_manager_instance.config.nb_config.session_id_cookie_name: "session_id"}

    # Use admin headers so the user can access the private remote pool.
    _, res = await sanic_client.post("/api/data/sessions/", json=data, headers=admin_headers, cookies=cookies)
    assert res.status_code == 201, res.text

    server_name: str = res.json["name"]

    # Fetch the created session from k8s and verify the readiness probe.
    # NOTE: The session is created under the admin user's namespace (safe_username="admin").
    session = await app_manager_instance.config.nb_config.k8s_v2_client.get_session(server_name, "admin")
    assert session.spec.session.readinessProbe.type == Type.http

    # Cleanup.
    _, res = await sanic_client.delete(f"/api/data/sessions/{server_name}", headers=admin_headers)
    assert res.status_code == 204, res.text


def create_test_environment(
    container_image: str, work_dir: PurePosixPath | None = None, mount_dir: PurePosixPath | None = None
) -> Environment:
    return Environment(
        name="test",
        container_image=container_image,
        default_url="test",
        id=ULID(),
        environment_image_source=EnvironmentImageSource.image,
        port=8888,
        uid=1000,
        gid=1000,
        environment_kind=EnvironmentKind.CUSTOM,
        creation_date=datetime.now(),
        created_by=Member(id="id"),
        build_parameters=None,
        build_parameters_id=None,
        mount_directory=mount_dir,
        working_directory=work_dir,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "environment,expected_mount_dir,expected_work_dir",
    [
        (
            create_test_environment("busybox:1.38"),
            PurePosixPath("/work"),
            PurePosixPath("/work"),
        ),
        (
            create_test_environment("ghcr.io/swissdatasciencecenter/renku/py-datascience-jupyterlab:2.17.3"),
            # The default work dir in the buildpack images is /workspace so we mount there
            PurePosixPath("/workspace"),
            PurePosixPath("/workspace"),
        ),
        (
            # If we set only the work dir on the environment that should be used
            create_test_environment(
                "ghcr.io/swissdatasciencecenter/renku/py-datascience-jupyterlab:2.17.3",
                work_dir=PurePosixPath("/home/renku/work"),
            ),
            PurePosixPath("/home/renku/work"),
            PurePosixPath("/home/renku/work"),
        ),
        (
            # If we set the work and mount dir on the environment that should be used
            create_test_environment(
                "ghcr.io/swissdatasciencecenter/renku/py-datascience-jupyterlab:2.17.3",
                mount_dir=PurePosixPath("/home/renku/work"),
                work_dir=PurePosixPath("/home/renku/work"),
            ),
            PurePosixPath("/home/renku/work"),
            PurePosixPath("/home/renku/work"),
        ),
        (
            # If the work dir is not inside the mount dir, the work dir will be set to the mount dir
            create_test_environment(
                "ghcr.io/swissdatasciencecenter/renku/py-datascience-jupyterlab:2.17.3",
                mount_dir=PurePosixPath("/home/renku/mount"),
                work_dir=PurePosixPath("/home/renku/work"),
            ),
            PurePosixPath("/home/renku/mount"),
            PurePosixPath("/home/renku/mount"),
        ),
        (
            create_test_environment(
                "ghcr.io/swissdatasciencecenter/renku/py-datascience-jupyterlab:2.17.3",
                mount_dir=PurePosixPath("/home/renku/mount"),
            ),
            PurePosixPath("/home/renku/mount"),
            PurePosixPath("/home/renku/mount"),
        ),
        (
            # If you try to mount on / we move it to /work to preven users from wiping out the whole image
            create_test_environment(
                "ghcr.io/swissdatasciencecenter/renku/py-datascience-jupyterlab:2.17.3",
                mount_dir=PurePosixPath("/"),
            ),
            PurePosixPath("/work"),
            PurePosixPath("/work"),
        ),
    ],
)
async def test_mount_workdir(
    environment: Environment,
    expected_mount_dir: PurePosixPath,
    expected_work_dir: PurePosixPath,
    app_manager_instance: DependencyManager,
    sanic_client: SanicASGITestClient,
) -> None:
    mount_dir, work_dir = await get_mount_work_dir(
        AnonymousAPIUser(id="anon-user"), environment, app_manager_instance.image_check_repo
    )
    assert mount_dir == expected_mount_dir
    assert work_dir == expected_work_dir
