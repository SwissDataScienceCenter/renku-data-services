"""Tests for connected services blueprints."""

from typing import Any
from urllib.parse import parse_qs, quote, quote_plus, urlparse

import pytest
import pytest_asyncio
from sanic import Sanic
from sanic_testing.testing import SanicASGITestClient

from renku_data_services.connected_services.dummy_async_oauth2_client import DummyAsyncOAuth2Client
from renku_data_services.data_api.app import register_all_handlers
from renku_data_services.data_api.dependencies import DependencyManager
from renku_data_services.migrations.core import run_migrations_for_app
from test.utils import SanicReusableASGITestClient


@pytest_asyncio.fixture(scope="session")
async def oauth2_test_client_setup(app_manager: DependencyManager) -> SanicASGITestClient:
    app_manager.async_oauth2_client_class = DummyAsyncOAuth2Client
    app_manager.connected_services_repo.async_oauth2_client_class = DummyAsyncOAuth2Client
    app = Sanic(app_manager.app_name)
    app = register_all_handlers(app, app_manager)
    async with SanicReusableASGITestClient(app) as client:
        yield client


@pytest.fixture
def oauth2_test_client(oauth2_test_client_setup, db_instance, authz_instance):
    run_migrations_for_app("common")
    return oauth2_test_client_setup


@pytest.fixture
def create_oauth2_provider(sanic_client: SanicASGITestClient, admin_headers):
    async def create_oauth2_provider_helper(provider_id: str, **payload) -> dict[str, Any]:
        payload = payload.copy()
        payload.update({"id": provider_id})
        payload["kind"] = payload.get("kind") or "gitlab"
        payload["client_id"] = payload.get("client_id") or "some-client-id"
        payload["client_secret"] = payload.get("client_secret") or "some-client-secret"
        payload["display_name"] = payload.get("display_name") or "my oauth2 application"
        payload["scope"] = payload.get("scope") or "api"
        payload["url"] = payload.get("url") or "https://example.org"
        payload["use_pkce"] = payload.get("use_pkce") or False
        _, res = await sanic_client.post("/api/data/oauth2/providers", headers=admin_headers, json=payload)

        assert res.status_code == 201, res.text
        assert res.json is not None
        return res.json

    return create_oauth2_provider_helper


@pytest.fixture
def create_oauth2_connection(oauth2_test_client: SanicASGITestClient, user_headers, create_oauth2_provider):
    async def create_oauth2_connection_helper(provider_id: str, **payload) -> dict[str, Any]:
        await create_oauth2_provider(provider_id, **payload)

        _, res = await oauth2_test_client.get(
            f"/api/data/oauth2/providers/{provider_id}/authorize", headers=user_headers
        )

        location = urlparse(res.headers["location"])
        query = parse_qs(location.query)
        state = query.get("state", [None])[0]
        qs = f"state={quote(state)}"

        _, res = await oauth2_test_client.get(f"/api/data/oauth2/callback?{qs}")

        _, res = await oauth2_test_client.get("/api/data/oauth2/connections", headers=user_headers)

        assert res.status_code == 200, res.text
        assert res.json is not None
        connection = None
        for conn in res.json:
            if conn["provider_id"] == provider_id:
                connection = conn
                break
        assert connection is not None
        assert connection.get("id") != ""
        assert connection.get("status") == "connected"

        return connection

    return create_oauth2_connection_helper


@pytest.mark.asyncio
async def test_get_repository_without_connection(
    mocker, oauth2_test_client: SanicASGITestClient, user_headers, create_oauth2_provider
):
    """Test getting internal Gitlab repository."""
    http_client = mocker.patch("renku_data_services.repositories.db.HttpClient")
    http_client.return_value = DummyAsyncOAuth2Client()

    await create_oauth2_provider("provider_1")
    repository_url = "https://example.org/username/my_repo.git"

    _, res = await oauth2_test_client.get(f"/api/data/repositories/{quote_plus(repository_url)}", headers=user_headers)

    assert res.status_code == 200, res.text
    assert res.json is not None
    result = res.json
    assert result["provider"]["id"] == "provider_1"
    assert "connection_id" not in result


@pytest.mark.asyncio
async def test_get_one_repository(oauth2_test_client: SanicASGITestClient, user_headers, create_oauth2_connection):
    connection = await create_oauth2_connection("provider_1")
    repository_url = "https://example.org/username/my_repo.git"

    _, res = await oauth2_test_client.get(f"/api/data/repositories/{quote_plus(repository_url)}", headers=user_headers)

    assert res.status_code == 200, res.text
    assert res.json is not None
    result = res.json
    assert result["connection"]["id"] == connection["id"]
    assert result["provider"]["id"] == "provider_1"
    assert result.get("metadata") is not None
    repository_metadata = result["metadata"]
    assert repository_metadata.get("git_url") == repository_url
    assert repository_metadata.get("pull_permission")
    assert not repository_metadata.get("push_permission")


@pytest.mark.asyncio
async def test_get_one_repository_not_found(
    oauth2_test_client: SanicASGITestClient, user_headers, create_oauth2_connection
):
    connection = await create_oauth2_connection("provider_1")
    repository_url = "https://example.org/username/another_repo.git"

    _, res = await oauth2_test_client.get(f"/api/data/repositories/{quote_plus(repository_url)}", headers=user_headers)

    assert res.status_code == 200, res.text
    assert res.json is not None
    result = res.json
    assert result["connection"]["id"] == connection["id"]
    assert result["provider"]["id"] == "provider_1"
    assert result.get("metadata") is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "repository_url,status_code",
    [
        ("https://github.com/SwissDataScienceCenter/renku.git", 200),
        ("https://example.org/does-not-exist.git", 404),
        ("http://foobar", 404),
    ],
)
async def test_get_one_repository_probe(sanic_client: SanicASGITestClient, repository_url, status_code):
    repository_url_param = quote_plus(repository_url)
    _, response = await sanic_client.get(f"/api/data/repositories/{repository_url_param}/probe")

    assert response.status_code == status_code, response.text
