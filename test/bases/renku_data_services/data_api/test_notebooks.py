"""Tests for notebook blueprints."""

import asyncio
import os

from collections.abc import AsyncIterator
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
import pytest_asyncio
from kr8s.asyncio.objects import Pod
from sanic_testing.testing import SanicASGITestClient

from renku_data_services.notebooks.api.classes.k8s_client import JupyterServerV1Alpha1Kr8s

from .utils import ClusterRequired, setup_amalthea

os.environ["KUBECONFIG"] = ".k3d-config.yaml"


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


@pytest_asyncio.fixture
async def jupyter_server(renku_image: str, server_name: str, pod_name: str) -> AsyncIterator[JupyterServerV1Alpha1Kr8s]:
    """Fake server to have the minimal set of objects for tests"""

    server = await JupyterServerV1Alpha1Kr8s(
        {
            "metadata": {"name": server_name, "labels": {"renku.io/safe-username": "user"}},
            "spec": {"jupyterServer": {"image": renku_image}, "routing": {"host": "locahost"}, "auth": {"token": ""}},
        }
    )

    await server.create()
    pod = await Pod(dict(metadata=dict(name=pod_name)))
    max_retries = 200
    sleep_seconds = 0.2
    retries = 0
    while True:
        retries += 1
        pod_exists = await pod.exists()
        if pod_exists:
            break
        if retries > max_retries:
            raise ValueError(
                f"The pod {pod_name} for the session {server_name} could not found even after {max_retries} "
                f"retries with {sleep_seconds} seconds of sleep after each retry."
            )
        await asyncio.sleep(sleep_seconds)
    await pod.refresh()
    await pod.wait("condition=Ready")
    yield server
    await server.delete("Foreground")


@pytest_asyncio.fixture()
async def practice_jupyter_server(renku_image: str, server_name: str) -> AsyncIterator[JupyterServerV1Alpha1Kr8s]:
    """Fake server for non pod related tests"""

    server = await JupyterServerV1Alpha1Kr8s(
        {
            "metadata": {
                "name": server_name,
                "labels": {"renku.io/safe-username": "user"},
                "annotations": {
                    "renku.io/branch": "dummy",
                    "renku.io/commit-sha": "sha",
                    "renku.io/default_image_used": "default/image",
                    "renku.io/namespace": "default",
                    "renku.io/projectName": "dummy",
                    "renku.io/repository": "dummy",
                },
            },
            "spec": {"jupyterServer": {"image": renku_image}},
        }
    )

    await server.create()
    yield server
    await server.delete("Foreground")


@pytest.fixture()
def authenticated_user_headers(user_headers):
    return dict({"Renku-Auth-Refresh-Token": "test-refresh-token"}, **user_headers)


@pytest.mark.asyncio
@pytest.mark.parametrize("image,expected_status_code", [("python:3.12", 200), ("shouldnotexist:0.42", 404)])
async def test_check_docker_image(sanic_client: SanicASGITestClient, user_headers, image, expected_status_code):
    """Validate that the images endpoint answers correctly.

    Needs the responses package in case docker queries must be mocked
    """

    _, res = await sanic_client.get(f"/api/data/notebooks/images/?image_url={image}", headers=user_headers)

    assert res.status_code == expected_status_code, res.text


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
    def amalthea(self, cluster) -> None:
        if cluster is not None:
            setup_amalthea("amalthea-js", "amalthea", "0.12.2", cluster)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "server_name_fixture,expected_status_code", [("unknown_server_name", 404), ("server_name", 200)]
    )
    async def test_log_retrieval(
        self,
        sanic_client: SanicASGITestClient,
        request,
        server_name_fixture,
        expected_status_code,
        jupyter_server,
        authenticated_user_headers,
    ):
        """Validate that the logs endpoint answers correctly"""

        server_name = request.getfixturevalue(server_name_fixture)

        _, res = await sanic_client.get(f"/api/data/notebooks/logs/{server_name}", headers=authenticated_user_headers)

        assert res.status_code == expected_status_code, res.text

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "server_name_fixture,expected_status_code", [("unknown_server_name", 404), ("server_name", 204)]
    )
    async def test_stop_server(
        self,
        sanic_client: SanicASGITestClient,
        request,
        server_name_fixture,
        expected_status_code,
        practice_jupyter_server,
        authenticated_user_headers,
    ):
        server_name = request.getfixturevalue(server_name_fixture)

        _, res = await sanic_client.delete(
            f"/api/data/notebooks/servers/{server_name}", headers=authenticated_user_headers
        )

        assert res.status_code == expected_status_code, res.text

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "server_name_fixture,expected_status_code, patch",
        [("unknown_server_name", 404, {}), ("server_name", 200, {"state": "hibernated"})],
    )
    async def test_patch_server(
        self,
        sanic_client: SanicASGITestClient,
        request,
        server_name_fixture,
        expected_status_code,
        patch,
        practice_jupyter_server,
        authenticated_user_headers,
    ):
        server_name = request.getfixturevalue(server_name_fixture)

        _, res = await sanic_client.patch(
            f"/api/data/notebooks/servers/{server_name}", json=patch, headers=authenticated_user_headers
        )

        assert res.status_code == expected_status_code, res.text


class AttributeDictionary(dict):
    """Enables accessing dictionary keys as attributes"""

    def __init__(self, dictionary):
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
        [value for _, value in self.items()]

    def __setitem__(self, k, v):
        if k == "list":
            raise ValueError("'list' is not allowed as a key")
        self.__setattr__(k, v)
        return super().__setitem__(k, v)


@pytest.fixture
def fake_gitlab_projects():
    class GitLabProject(AttributeDictionary):
        def __init__(self):
            super().__init__({})

        def get(self, name, default=None):
            if name not in self:
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
            return super().get(name, default)

    return GitLabProject()


@pytest.fixture()
def fake_gitlab(mocker, fake_gitlab_projects):
    gitlab = mocker.patch("renku_data_services.notebooks.api.classes.user.Gitlab")
    gitlab_mock = MagicMock()
    gitlab_mock.auth = MagicMock()
    gitlab_mock.projects = fake_gitlab_projects
    gitlab_mock.user = AttributeDictionary(
        {"username": "john.doe", "name": "John Doe", "email": "john.doe@notebooks-tests.renku.ch"}
    )
    gitlab_mock.url = "https://gitlab-url.com"
    gitlab.return_value = gitlab_mock
    return gitlab


@pytest.mark.asyncio
async def test_old_start_server(sanic_client: SanicASGITestClient, authenticated_user_headers, fake_gitlab):
    data = {
        "branch": "main",
        "commit_sha": "ee4b1c9fedc99abe5892ee95320bbd8471c5985b",
        "namespace": "test-namespace",
        "project": "my-test",
        "image": "alpine:3",
    }

    _, res = await sanic_client.post("/api/data/notebooks/old/servers/", json=data, headers=authenticated_user_headers)

    assert res.status_code == 201, res.text

    server_name = res.json["name"]
    _, res = await sanic_client.delete(f"/api/data/notebooks/servers/{server_name}", headers=authenticated_user_headers)

    assert res.status_code == 204, res.text


@pytest.mark.asyncio
async def test_start_server(sanic_client: SanicASGITestClient, authenticated_user_headers, fake_gitlab):
    data = {
        "branch": "main",
        "commit_sha": "ee4b1c9fedc99abe5892ee95320bbd8471c5985b",
        "project_id": "test-namespace/my-test",
        "launcher_id": "test_launcher",
        "image": "alpine:3",
    }

    _, res = await sanic_client.post("/api/data/notebooks/servers/", json=data, headers=authenticated_user_headers)

    assert res.status_code == 201, res.text

    server_name = res.json["name"]
    _, res = await sanic_client.delete(f"/api/data/notebooks/servers/{server_name}", headers=authenticated_user_headers)

    assert res.status_code == 204, res.text
