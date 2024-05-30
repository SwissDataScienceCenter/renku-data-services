"""Tests for connected services blueprints."""

from typing import Any
from urllib.parse import parse_qs, quote, urlparse

import pytest
from sanic import Sanic
from sanic_testing.testing import SanicASGITestClient

from renku_data_services.app_config import Config
from renku_data_services.connected_services.dummy_async_oauth2_client import DummyAsyncOAuth2Client
from renku_data_services.data_api.app import register_all_handlers


@pytest.fixture
def oauth2_test_client(app_config: Config) -> SanicASGITestClient:
    app_config.async_oauth2_client_class = DummyAsyncOAuth2Client
    app = Sanic(app_config.app_name)
    app = register_all_handlers(app, app_config)
    return SanicASGITestClient(app)


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
async def test_get_all_oauth2_providers(
    sanic_client: SanicASGITestClient, unauthorized_headers, create_oauth2_provider
) -> None:
    await create_oauth2_provider("provider_1")
    await create_oauth2_provider("provider_2")
    await create_oauth2_provider("provider_3")

    _, res = await sanic_client.get("/api/data/oauth2/providers", headers=unauthorized_headers)

    assert res.status_code == 200, res.text
    assert res.json is not None
    providers = res.json
    assert {p["id"] for p in providers} == {
        "provider_1",
        "provider_2",
        "provider_3",
    }


@pytest.mark.asyncio
async def test_get_oauth2_provider(
    sanic_client: SanicASGITestClient, unauthorized_headers, create_oauth2_provider
) -> None:
    provider = await create_oauth2_provider(
        "provider_1",
        display_name="Some external service",
        url="https://my-example.org",
    )
    provider_id = provider["id"]

    _, res = await sanic_client.get(f"/api/data/oauth2/providers/{provider_id}", headers=unauthorized_headers)

    assert res.status_code == 200, res.text
    assert res.json is not None
    assert res.json.get("id") == "provider_1"
    assert res.json.get("display_name") == "Some external service"
    assert res.json.get("url") == "https://my-example.org"


@pytest.mark.asyncio
async def test_post_oauth2_provider(sanic_client: SanicASGITestClient, admin_headers) -> None:
    payload = {
        "id": "some-provider",
        "kind": "gitlab",
        "client_id": "some-client-id",
        "client_secret": "some-client-secret",
        "display_name": "Some external service",
        "scope": "api",
        "url": "https://example.org",
        "use_pkce": False,
    }

    _, res = await sanic_client.post("/api/data/oauth2/providers", headers=admin_headers, json=payload)

    assert res.status_code == 201, res.text
    assert res.json is not None
    assert res.json.get("id") == "some-provider"
    assert res.json.get("kind") == "gitlab"
    assert res.json.get("client_id") == "some-client-id"
    assert res.json.get("client_secret") == "redacted"
    assert res.json.get("display_name") == "Some external service"
    assert res.json.get("scope") == "api"
    assert res.json.get("url") == "https://example.org"


@pytest.mark.asyncio
async def test_post_oauth2_provider_unauthorized(sanic_client: SanicASGITestClient, user_headers) -> None:
    payload = {
        "id": "some-provider",
        "kind": "gitlab",
        "client_id": "some-client-id",
        "client_secret": "some-client-secret",
        "display_name": "Some external service",
        "scope": "api",
        "url": "https://example.org",
    }

    _, res = await sanic_client.post("/api/data/oauth2/providers", headers=user_headers, json=payload)

    assert res.status_code == 401, res.text


@pytest.mark.asyncio
async def test_patch_oauth2_provider(sanic_client: SanicASGITestClient, admin_headers, create_oauth2_provider) -> None:
    provider = await create_oauth2_provider("provider_1")
    provider_id = provider["id"]

    payload = {
        "display_name": "New display name",
        "scope": "read write",
        "url": "https://my-new-example.org",
    }

    _, res = await sanic_client.patch(f"/api/data/oauth2/providers/{provider_id}", headers=admin_headers, json=payload)

    assert res.status_code == 200, res.text
    assert res.json is not None
    assert res.json.get("display_name") == "New display name"
    assert res.json.get("scope") == "read write"
    assert res.json.get("url") == "https://my-new-example.org"


@pytest.mark.asyncio
async def test_patch_oauth2_provider_unauthorized(
    sanic_client: SanicASGITestClient, user_headers, create_oauth2_provider
) -> None:
    provider = await create_oauth2_provider("provider_1")
    provider_id = provider["id"]

    payload = {
        "display_name": "New display name",
        "scope": "read write",
        "url": "https://my-new-example.org",
    }

    _, res = await sanic_client.patch(f"/api/data/oauth2/providers/{provider_id}", headers=user_headers, json=payload)

    assert res.status_code == 401, res.text


@pytest.mark.asyncio
async def test_delete_oauth2_provider(sanic_client: SanicASGITestClient, admin_headers, create_oauth2_provider) -> None:
    provider = await create_oauth2_provider("provider_1")
    provider_id = provider["id"]

    _, res = await sanic_client.delete(f"/api/data/oauth2/providers/{provider_id}", headers=admin_headers)

    assert res.status_code == 204, res.text


@pytest.mark.asyncio
async def test_delete_oauth2_provider_unauthorized(
    sanic_client: SanicASGITestClient, user_headers, create_oauth2_provider
) -> None:
    provider = await create_oauth2_provider("provider_1")
    provider_id = provider["id"]

    _, res = await sanic_client.delete(f"/api/data/oauth2/providers/{provider_id}", headers=user_headers)

    assert res.status_code == 401, res.text


@pytest.mark.asyncio
async def test_start_oauth2_authorization_flow(
    sanic_client: SanicASGITestClient, user_headers, create_oauth2_provider
) -> None:
    provider = await create_oauth2_provider("provider_1")
    provider_id = provider["id"]

    _, res = await sanic_client.get(f"/api/data/oauth2/providers/{provider_id}/authorize", headers=user_headers)

    assert res.status_code == 302, res.text
    assert "location" in res.headers
    location = urlparse(res.headers["location"])
    assert location.scheme == "https"
    assert location.netloc == "example.org"
    assert location.path == "/oauth/authorize"
    assert location.query != ""
    query = parse_qs(location.query)
    assert query.get("client_id", [None])[0] == "some-client-id"
    assert query.get("redirect_uri", [None])[0] is not None
    redirect_uri = urlparse(query.get("redirect_uri", [None])[0])
    assert redirect_uri.path == "/api/data/oauth2/callback"
    assert query.get("response_type", [None])[0] == "code"
    assert query.get("scope", [None])[0] == "api"
    assert query.get("state", [None])[0] != ""

    _, res = await sanic_client.get("/api/data/oauth2/connections", headers=user_headers)

    assert res.status_code == 200, res.text
    assert res.json is not None
    connection = None
    for conn in res.json:
        if conn["provider_id"] == provider_id:
            connection = conn
            break
    assert connection is not None
    assert connection.get("id") != ""
    assert connection.get("status") == "pending"


@pytest.mark.asyncio
async def test_callback_oauth2_authorization_flow(
    oauth2_test_client: SanicASGITestClient, user_headers, create_oauth2_provider
):
    provider = await create_oauth2_provider("provider_1")
    provider_id = provider["id"]

    next_url = "https://example.org"
    qs = f"next_url={quote(next_url)}"

    _, res = await oauth2_test_client.get(
        f"/api/data/oauth2/providers/{provider_id}/authorize?{qs}", headers=user_headers
    )

    assert res.status_code == 302, res.text
    assert "location" in res.headers
    location = urlparse(res.headers["location"])
    query = parse_qs(location.query)
    state = query.get("state", [None])[0]
    assert state != ""

    qs = f"state={quote(state)}"

    _, res = await oauth2_test_client.get(f"/api/data/oauth2/callback?{qs}")

    assert res.status_code == 302, res.text
    assert "location" in res.headers
    assert res.headers["location"] == "https://example.org"

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

    connection_id = connection["id"]

    _, res = await oauth2_test_client.get(f"/api/data/oauth2/connections/{connection_id}/token", headers=user_headers)

    assert res.status_code == 200, res.text
    assert res.json is not None
    token_set = res.json
    assert token_set.get("access_token") == "ACCESS_TOKEN"


@pytest.mark.asyncio
async def test_get_account(oauth2_test_client: SanicASGITestClient, user_headers, create_oauth2_connection):
    connection = await create_oauth2_connection("provider_1")
    connection_id = connection["id"]

    _, res = await oauth2_test_client.get(f"/api/data/oauth2/connections/{connection_id}/account", headers=user_headers)

    assert res.status_code == 200, res.text
    assert res.json is not None
    account = res.json
    assert account.get("username") == "USERNAME"
    assert account.get("web_url") == "https://example.org/USERNAME"
