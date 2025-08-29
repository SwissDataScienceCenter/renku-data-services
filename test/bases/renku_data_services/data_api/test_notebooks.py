"""Tests for notebook blueprints."""

import asyncio
import contextlib
from collections.abc import AsyncGenerator, AsyncIterator, Generator
from contextlib import suppress
from datetime import timedelta
from unittest.mock import MagicMock
from uuid import uuid4

import kr8s
import pytest
import pytest_asyncio
from kr8s import NotFoundError
from sanic_testing.testing import SanicASGITestClient

from renku_data_services.k8s.clients import K8sClusterClient
from renku_data_services.k8s.constants import DEFAULT_K8S_CLUSTER
from renku_data_services.k8s.models import ClusterConnection
from renku_data_services.k8s.watcher import K8sWatcher, k8s_object_handler
from renku_data_services.notebooks.api.classes.k8s_client import JupyterServerV1Alpha1Kr8s
from renku_data_services.notebooks.constants import JUPYTER_SESSION_GVK

from .utils import ClusterRequired, setup_amalthea


@pytest.fixture(scope="module", autouse=True)
def kubeconfig(monkeysession):
    monkeysession.setenv("KUBECONFIG", ".k3d-config.yaml")


@pytest.fixture
def non_mocked_hosts() -> list:
    """Hosts that should not get mocked during tests."""

    return ["127.0.0.1"]


@pytest.fixture
def renku_image() -> str:
    return "renku/renkulab-py:3.10-0.24.0"


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
async def jupyter_server(renku_image: str, server_name: str) -> AsyncIterator[JupyterServerV1Alpha1Kr8s]:
    """Fake server for non pod related tests"""

    server = await JupyterServerV1Alpha1Kr8s(
        {
            "metadata": {
                "name": server_name,
                "labels": {"renku.io/safe-username": "user", "renku.io/userId": "user"},
                "annotations": {
                    "renku.io/branch": "dummy",
                    "renku.io/commit-sha": "sha",
                    "renku.io/default_image_used": "default/image",
                    "renku.io/namespace": "default",
                    "renku.io/projectName": "dummy",
                    "renku.io/repository": "dummy",
                },
            },
            "spec": {
                "jupyterServer": {
                    "image": renku_image,
                    "resources": {
                        "requests": {
                            "cpu": 0.1,
                            "memory": 100_000_000,
                        },
                    },
                },
            },
        }
    )

    await server.create()
    yield server
    # NOTE: This is used also in tests that check if the server was properly stopped
    # in this case the server will already be gone when we try to delete it in the cleanup here.
    with suppress(NotFoundError):
        await server.delete("Foreground")


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


@pytest.fixture
def fake_gitlab_project_info():
    return AttributeDictionary(
        {
            "path": "my-test",
            "path_with_namespace": "test-namespace/my-test",
            "branches": {"main": AttributeDictionary({})},
            "commits": {"ee4b1c9fedc99abe5892ee95320bbd8471c5985b": AttributeDictionary({})},
            "id": 5407,
            "http_url_to_repo": "https://gitlab-url.com/test-namespace/my-test.git",
            "web_url": "https://gitlab-url.com/test-namespace/my-test",
        }
    )


@pytest.fixture
def fake_gitlab_projects(fake_gitlab_project_info):
    class GitLabProject(AttributeDictionary):
        def __init__(self):
            super().__init__({})

        def get(self, name, default=None):
            if name not in self:
                return fake_gitlab_project_info
            return super().get(name, default)

    return GitLabProject()


@pytest.fixture()
def fake_gitlab(mocker, fake_gitlab_projects, fake_gitlab_project_info):
    gitlab = mocker.patch("renku_data_services.notebooks.api.classes.user.Gitlab")
    get_project = mocker.patch("renku_data_services.notebooks.api.classes.user._get_project")
    gitlab_mock = MagicMock()
    gitlab_mock.auth = MagicMock()
    gitlab_mock.projects = fake_gitlab_projects
    gitlab_mock.user = AttributeDictionary(
        {"username": "john.doe", "name": "John Doe", "email": "john.doe@notebooks-tests.renku.ch"}
    )
    gitlab_mock.url = "https://gitlab-url.com"
    gitlab.return_value = gitlab_mock
    get_project.return_value = fake_gitlab_project_info
    return gitlab


async def wait_for(sanic_client: SanicASGITestClient, user_headers, server_name: str, max_timeout: int = 20):
    res = None
    waited = 0
    for t in list(range(0, max_timeout)):
        waited = t + 1
        _, res = await sanic_client.get("/api/data/notebooks/servers", headers=user_headers)
        if res.status_code == 200 and res.json["servers"].get(server_name) is not None:
            return
        await asyncio.sleep(1)  # wait a bit for k8s events to be processed in the background

    raise Exception(
        f"Timeout reached while waiting for {server_name} to be ready."
        f" res {res.json if res is not None else None}, waited {waited} seconds"
    )


@pytest.mark.asyncio
async def test_version(sanic_client: SanicASGITestClient, user_headers):
    _, res = await sanic_client.get("/api/data/notebooks/version", headers=user_headers)

    assert res.status_code == 200, res.text

    assert res.json == {
        "name": "renku-notebooks",
        "versions": [
            {
                "data": {
                    "anonymousSessionsEnabled": False,
                    "cloudstorageClass": "csi-rclone",
                    "cloudstorageEnabled": False,
                    "defaultCullingThresholds": {
                        "anonymous": {
                            "hibernation": 1,
                            "idle": 86400,
                        },
                        "registered": {
                            "hibernation": 86400,
                            "idle": 86400,
                        },
                    },
                    "sshEnabled": False,
                },
                "version": "0.0.0",
            },
        ],
    }


@pytest.mark.asyncio
async def test_server_options(sanic_client: SanicASGITestClient, user_headers):
    _, res = await sanic_client.get("/api/data/notebooks/server_options", headers=user_headers)

    assert res.status_code == 200, res.text
    assert res.json == {
        "cloudstorage": {"enabled": False},
        "defaultUrl": {
            "default": "/lab",
            "displayName": "Default Environment",
            "options": ["/lab"],
            "order": 1,
            "type": "enum",
        },
        "lfs_auto_fetch": {
            "default": False,
            "displayName": "Automatically fetch LFS data",
            "order": 6,
            "type": "boolean",
        },
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("image,expected_status_code", [("python:3.12", 200), ("shouldnotexist:0.42", 404)])
async def test_check_docker_image(sanic_client: SanicASGITestClient, user_headers, image, expected_status_code):
    """Validate that the images endpoint answers correctly.

    Needs the responses package in case docker queries must be mocked
    """

    _, res = await sanic_client.get(f"/api/data/notebooks/images/?image_url={image}", headers=user_headers)

    assert res.status_code == expected_status_code, res.text


class TestNotebooks(ClusterRequired):
    @pytest.fixture(scope="class", autouse=True)
    def amalthea(self, cluster, app_manager) -> Generator[None, None]:
        if cluster is not None:
            setup_amalthea("amalthea-js", "amalthea", "0.21.0", cluster)
        app_manager.config.nb_config._kr8s_api.push(asyncio.run(kr8s.asyncio.api()))

        yield
        app_manager.config.nb_config._kr8s_api.pop()

    @pytest_asyncio.fixture(scope="class", autouse=True)
    async def k8s_watcher(self, amalthea, app_manager) -> AsyncGenerator[None, None]:
        clusters = {
            DEFAULT_K8S_CLUSTER: K8sClusterClient(
                ClusterConnection(
                    id=DEFAULT_K8S_CLUSTER,
                    namespace=app_manager.config.nb_config.k8s.renku_namespace,
                    api=app_manager.config.nb_config._kr8s_api.current,
                )
            )
        }

        # sleep to give amalthea a chance to create the CRDs, otherwise the watcher can error out
        await asyncio.sleep(1)
        watcher = K8sWatcher(
            handler=k8s_object_handler(
                app_manager.config.nb_config.k8s_db_cache, app_manager.metrics, app_manager.rp_repo
            ),
            clusters=clusters,
            kinds=[JUPYTER_SESSION_GVK],
            db_cache=app_manager.config.nb_config.k8s_db_cache,
        )
        asyncio.create_task(watcher.start())
        yield
        with contextlib.suppress(TimeoutError):
            await watcher.stop(timeout=timedelta(seconds=1))

    @pytest.mark.asyncio
    async def test_user_server_list(
        self, sanic_client: SanicASGITestClient, authenticated_user_headers, fake_gitlab, jupyter_server
    ):
        """Validate that the user server list endpoint answers correctly"""

        await asyncio.sleep(1)  # wait a bit for k8s events to be processed in the background

        _, res = await sanic_client.get("/api/data/notebooks/servers", headers=authenticated_user_headers)

        assert res.status_code == 200, res.text
        assert "servers" in res.json
        assert len(res.json["servers"]) == 1

    @pytest.mark.asyncio
    @pytest.mark.parametrize("server_exists,expected_status_code", [(False, 404), (True, 200)])
    async def test_log_retrieval(
        self,
        sanic_client: SanicASGITestClient,
        server_exists,
        jupyter_server,
        expected_status_code,
        authenticated_user_headers,
        fake_gitlab,
    ):
        """Validate that the logs endpoint answers correctly"""

        server_name = "unknown_server"
        if server_exists:
            server_name = jupyter_server.name
            await wait_for(sanic_client, authenticated_user_headers, server_name)

        _, res = await sanic_client.get(f"/api/data/notebooks/logs/{server_name}", headers=authenticated_user_headers)

        assert res.status_code == expected_status_code, res.text

    @pytest.mark.asyncio
    @pytest.mark.parametrize("server_exists,expected_status_code", [(False, 204), (True, 204)])
    async def test_stop_server(
        self,
        sanic_client: SanicASGITestClient,
        server_exists,
        jupyter_server,
        expected_status_code,
        authenticated_user_headers,
        fake_gitlab,
    ):
        server_name = "unknown_server"
        if server_exists:
            server_name = jupyter_server.name

        _, res = await sanic_client.delete(
            f"/api/data/notebooks/servers/{server_name}", headers=authenticated_user_headers
        )

        assert res.status_code == expected_status_code, res.text

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "server_exists,expected_status_code, patch",
        [(False, 404, {}), (True, 200, {"state": "hibernated"})],
    )
    async def test_patch_server(
        self,
        sanic_client: SanicASGITestClient,
        server_exists,
        jupyter_server,
        expected_status_code,
        patch,
        authenticated_user_headers,
        fake_gitlab,
    ):
        server_name = "unknown_server"
        if server_exists:
            server_name = jupyter_server.name
            await wait_for(sanic_client, authenticated_user_headers, server_name)

        _, res = await sanic_client.patch(
            f"/api/data/notebooks/servers/{server_name}", json=patch, headers=authenticated_user_headers
        )

        assert res.status_code == expected_status_code, res.text

    @pytest.mark.asyncio
    async def test_start_server(self, sanic_client: SanicASGITestClient, authenticated_user_headers, fake_gitlab):
        data = {
            "branch": "main",
            "commit_sha": "ee4b1c9fedc99abe5892ee95320bbd8471c5985b",
            "namespace": "test-ns-start-server",
            "project": "my-test",
            "image": "alpine:3",
        }

        _, res = await sanic_client.post("/api/data/notebooks/servers/", json=data, headers=authenticated_user_headers)

        assert res.status_code == 201, res.text

        server_name: str = res.json["name"]
        _, res = await sanic_client.delete(
            f"/api/data/notebooks/servers/{server_name}", headers=authenticated_user_headers
        )

        assert res.status_code == 204, res.text
