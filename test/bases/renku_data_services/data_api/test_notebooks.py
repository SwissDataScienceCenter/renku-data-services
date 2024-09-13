"""Tests for notebook blueprints."""

import re
from unittest.mock import MagicMock

import pytest
from kr8s.objects import Pod, new_class
from pytest_httpx import HTTPXMock
from sanic_testing.testing import SanicASGITestClient

from .utils import AttributeDictionary

JupyterServer = new_class(
    kind="JupyterServer",
    version="amalthea.dev/v1alpha1",
    namespaced=True,
)


@pytest.fixture
def non_mocked_hosts() -> list:
    """Hosts that should not get mocked during tests."""

    return ["127.0.0.1"]


@pytest.fixture(scope="module")
def jupyter_server():
    """Fake server to have the minimal set of objects for tests"""

    session_name = "test-session"

    jupyter_server = JupyterServer(
        {
            "metadata": {"name": session_name, "labels": {"renku.io/safe-username": "user"}},
            "spec": {"jupyterServer": {"image": "alpine:3"}},
        }
    )

    pod = Pod(
        {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {"name": f"{session_name}-0", "labels": {"renku.io/safe-username": "user"}},
            "spec": {
                "containers": [
                    {
                        "name": "main",
                        "image": "alpine:3",
                        "command": ["sh", "-c", 'echo "Hello, Kubernetes!" && sleep 3600'],
                    }
                ],
            },
        }
    )

    pod.create()
    pod.wait("condition=Ready")

    jupyter_server.create()
    yield session_name
    pod.delete()
    jupyter_server.delete()


@pytest.fixture()
def dummy_jupyter_server():
    """Dummy server for non pod related tests"""

    session_name = "dummy-server"

    jupyter_server = JupyterServer(
        {
            "metadata": {
                "name": session_name,
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
            "spec": {"jupyterServer": {"image": "debian:bookworm"}},
        }
    )

    jupyter_server.create()
    yield session_name
    jupyter_server.delete()


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
@pytest.mark.parametrize("server_name,expected_status_code", [("unknown", 404), ("test-session", 200)])
async def test_log_retrieval(
    sanic_client: SanicASGITestClient,
    httpx_mock: HTTPXMock,
    server_name,
    expected_status_code,
    jupyter_server,
    authenticated_user_headers,
):
    """Validate that the logs endpoint answers correctly"""

    httpx_mock.add_response(url=f"http://not.specified/servers/{server_name}", json={}, status_code=400)

    _, res = await sanic_client.get(f"/api/data/notebooks/logs/{server_name}", headers=authenticated_user_headers)

    assert res.status_code == expected_status_code, res.text


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
@pytest.mark.parametrize("server_name,expected_status_code", [("unknown", 404), ("dummy-server", 204)])
async def test_stop_server(
    sanic_client: SanicASGITestClient,
    server_name,
    expected_status_code,
    dummy_jupyter_server,
    authenticated_user_headers,
    httpx_mock,
):
    httpx_mock.add_response(url=f"http://not.specified/servers/{server_name}", json={}, status_code=400)

    _, res = await sanic_client.delete(f"/api/data/notebooks/servers/{server_name}", headers=authenticated_user_headers)

    assert res.status_code == expected_status_code, res.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "server_name,expected_status_code, patch", [("unknown", 404, {}), ("dummy-server", 200, {"state": "hibernated"})]
)
async def test_patch_server(
    sanic_client: SanicASGITestClient,
    server_name,
    expected_status_code,
    patch,
    dummy_jupyter_server,
    authenticated_user_headers,
    httpx_mock,
):
    httpx_mock.add_response(url=f"http://not.specified/servers/{server_name}", json={}, status_code=400)

    _, res = await sanic_client.patch(
        f"/api/data/notebooks/servers/{server_name}", json=patch, headers=authenticated_user_headers
    )

    assert res.status_code == expected_status_code, res.text


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
async def test_start_server(
    sanic_client: SanicASGITestClient, httpx_mock: HTTPXMock, authenticated_user_headers, fake_gitlab
):
    httpx_mock.add_response(url=re.compile("http://not\\.specified/servers/.*"), json={}, status_code=400)

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
