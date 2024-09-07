"""Tests for notebook blueprints."""

import pytest
from kr8s.objects import Pod, new_class
from pytest_httpx import HTTPXMock
from sanic_testing.testing import SanicASGITestClient

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
            "spec": {"jupyterServer": {"image": "debian/bookworm"}},
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
def authenticated_user_headers(user_headers):
    return dict({"Renku-Auth-Refresh-Token": "test-refresh-token"}, **user_headers)


@pytest.mark.asyncio
@pytest.mark.parametrize("image,expected_status_code", [("python:3.12", 200), ("shouldnotexist:0.42", 404)])
async def test_check_docker_image(sanic_client: SanicASGITestClient, user_headers, image, expected_status_code):
    """Validate that the images endpoint answers correctly."""

    _, res = await sanic_client.get(f"/api/data/notebooks/images/?image_url={image}", headers=user_headers)

    assert res.status_code == expected_status_code, res.text


@pytest.mark.asyncio
@pytest.mark.parametrize("server_name,expected_status_code", [("unknown", 404), ("test-session", 200)])
async def test_log_retrieval(
    sanic_client: SanicASGITestClient,
    httpx_mock: HTTPXMock,
    user_headers,
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
