"""Tests for notebook blueprints."""

from unittest.mock import MagicMock

import pytest
from sanic_testing.testing import SanicASGITestClient


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


async def _create_server(sanic_client: SanicASGITestClient, server_exists: bool, authenticated_user_headers) -> str:
    if server_exists:
        data = {
            "branch": "main",
            "commit_sha": "ee4b1c9fedc99abe5892ee95320bbd8471c5985b",
            "namespace": "test-namespace",
            "project": "my-test",
            "image": "alpine:3",
        }
        _, res = await sanic_client.post("/api/data/notebooks/servers/", json=data, headers=authenticated_user_headers)
        return res.json["name"]
    else:
        return "unknown_server"


async def _delete_server(
    sanic_client: SanicASGITestClient, server_exists: bool, server_name: str, authenticated_user_headers
) -> None:
    if server_exists:
        _, res = await sanic_client.delete(
            f"/api/data/notebooks/servers/{server_name}", headers=authenticated_user_headers
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


class TestNotebooks:
    @pytest.mark.asyncio
    async def test_user_server_list(
        self,
        sanic_client: SanicASGITestClient,
        authenticated_user_headers,
        fake_gitlab,
    ):
        """Validate that the user server list endpoint answers correctly"""
        data = {
            "branch": "main",
            "commit_sha": "ee4b1c9fedc99abe5892ee95320bbd8471c5985b",
            "namespace": "test-namespace",
            "project": "my-test",
            "image": "alpine:3",
        }
        _, res = await sanic_client.post("/api/data/notebooks/servers/", json=data, headers=authenticated_user_headers)
        assert res.status_code == 201, res.text
        server_name: str = res.json["name"]

        _, res = await sanic_client.get("/api/data/notebooks/servers", headers=authenticated_user_headers)
        assert res.status_code == 200, res.text
        assert "servers" in res.json
        assert len(res.json["servers"]) == 1

        _, res = await sanic_client.delete(
            f"/api/data/notebooks/servers/{server_name}", headers=authenticated_user_headers
        )
        assert res.status_code == 204, res.text

    @pytest.mark.asyncio
    @pytest.mark.parametrize("server_exists,expected_status_code", [(False, 404), (True, 200)])
    async def test_log_retrieval(
        self,
        sanic_client: SanicASGITestClient,
        server_exists,
        expected_status_code,
        authenticated_user_headers,
        fake_gitlab,
    ):
        """Validate that the logs endpoint answers correctly"""

        server_name = await _create_server(sanic_client, server_exists, authenticated_user_headers)

        _, res = await sanic_client.get(f"/api/data/notebooks/logs/{server_name}", headers=authenticated_user_headers)

        assert res.status_code == expected_status_code, res.text

        await _delete_server(sanic_client, server_exists, server_name, authenticated_user_headers)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("server_exists,expected_status_code", [(False, 404), (True, 204)])
    async def test_stop_server(
        self,
        sanic_client: SanicASGITestClient,
        server_exists,
        expected_status_code,
        authenticated_user_headers,
        fake_gitlab,
    ):
        server_name = await _create_server(sanic_client, server_exists, authenticated_user_headers)

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
        expected_status_code,
        patch,
        authenticated_user_headers,
        fake_gitlab,
    ):
        server_name = await _create_server(sanic_client, server_exists, authenticated_user_headers)

        _, res = await sanic_client.patch(
            f"/api/data/notebooks/servers/{server_name}", json=patch, headers=authenticated_user_headers
        )

        assert res.status_code == expected_status_code, res.text

        await _delete_server(sanic_client, server_exists, server_name, authenticated_user_headers)

    @pytest.mark.asyncio
    async def test_start_server(self, sanic_client: SanicASGITestClient, authenticated_user_headers, fake_gitlab):
        data = {
            "branch": "main",
            "commit_sha": "ee4b1c9fedc99abe5892ee95320bbd8471c5985b",
            "namespace": "test-namespace",
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
