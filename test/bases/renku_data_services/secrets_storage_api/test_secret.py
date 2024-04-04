"""Tests for secrets blueprints."""

import json
from test.bases.renku_data_services.keycloak_sync.test_sync import get_kc_users
from typing import Any

import pytest
import pytest_asyncio
from sanic import Sanic
from sanic_testing.testing import SanicASGITestClient

from renku_data_services.secrets_storage.app_config import Config
from renku_data_services.secrets_storage_api.app import register_all_handlers
from renku_data_services.users.dummy_kc_api import DummyKeycloakAPI
from renku_data_services.users.models import UserInfo


@pytest.fixture
def users() -> list[UserInfo]:
    return [
        UserInfo("admin", "Admin", "Doe", "admin.doe@gmail.com"),
        UserInfo("user", "User", "Doe", "user.doe@gmail.com"),
        UserInfo("member-1", "Member-1", "Doe", "member-1.doe@gmail.com"),
        UserInfo("member-2", "Member-2", "Doe", "member-2.doe@gmail.com"),
    ]


@pytest_asyncio.fixture
async def sanic_client(
    secrets_storage_app_config: Config, users: list[UserInfo]
) -> SanicASGITestClient:
    secrets_storage_app_config.kc_api = DummyKeycloakAPI(users=get_kc_users(users))
    app = Sanic(secrets_storage_app_config.app_name)
    app = register_all_handlers(app, secrets_storage_app_config)
    # await app_config.kc_user_repo.initialize(app_config.kc_api)
    return SanicASGITestClient(app)


@pytest.fixture
def admin_headers() -> dict[str, str]:
    """Authentication headers for an admin user."""
    access_token = json.dumps({"is_admin": True, "id": "admin", "name": "Admin User"})
    return {"Authorization": f"Bearer {access_token}"}


@pytest.fixture
def user_headers() -> dict[str, str]:
    """Authentication headers for a normal user."""
    access_token = json.dumps({"is_admin": False, "id": "user", "name": "Normal User"})
    return {"Authorization": f"Bearer {access_token}"}


@pytest.fixture
def unauthorized_headers() -> dict[str, str]:
    """Authentication headers for an anonymous user (did not log in)."""
    return {"Authorization": "Bearer {}"}


@pytest.fixture
def create_secret(sanic_client: SanicASGITestClient, user_headers):
    async def create_secret_helper(name: str, value: str) -> dict[str, Any]:
        payload = {"name": name, "value": value}

        _, response = await sanic_client.post(
            "/api/secret/secrets", headers=user_headers, json=payload
        )

        assert response.status_code == 201, response.text
        return response.json

    return create_secret_helper


@pytest.mark.asyncio
async def test_create_secrets(sanic_client: SanicASGITestClient, user_headers):
    payload = {
        "name": "my-secret",
        "value": "42",
    }
    _, response = await sanic_client.post(
        "/api/secret/secrets", headers=user_headers, json=payload
    )

    assert response.status_code == 201, response.text
    assert response.json is not None
    assert response.json["name"] == "my-secret"
    assert response.json["value"] == "42"
    assert response.json["id"] is not None
    assert response.json["modification_date"] is not None


@pytest.mark.asyncio
async def test_get_one_secret(
    sanic_client: SanicASGITestClient, user_headers, create_secret
):
    await create_secret("secret-1", "value-1")
    secret = await create_secret("secret-2", "value-2")
    await create_secret("secret-3", "value-3")

    secret_id = secret["id"]

    _, response = await sanic_client.get(
        f"/api/secret/secrets/{secret_id}", headers=user_headers
    )

    assert response.status_code == 200, response.text
    assert response.json is not None
    assert response.json["name"] == "secret-2"
    assert response.json["value"] == "value-2"
    assert response.json["id"] == secret_id


@pytest.mark.asyncio
async def test_get_all_secrets(
    sanic_client: SanicASGITestClient, user_headers, create_secret
):
    await create_secret("secret-1", "value-1")
    await create_secret("secret-2", "value-2")
    await create_secret("secret-3", "value-3")

    _, response = await sanic_client.get("/api/secret/secrets", headers=user_headers)

    assert response.status_code == 200, response.text
    assert response.json is not None
    assert {s["name"] for s in response.json} == {"secret-1", "secret-2", "secret-3"}
    assert {s["value"] for s in response.json} == {"value-1", "value-2", "value-3"}


@pytest.mark.asyncio
async def test_get_delete_a_secret(
    sanic_client: SanicASGITestClient, user_headers, create_secret
):
    await create_secret("secret-1", "value-1")
    secret = await create_secret("secret-2", "value-2")
    await create_secret("secret-3", "value-3")

    secret_id = secret["id"]

    _, response = await sanic_client.delete(
        f"/api/secret/secrets/{secret_id}", headers=user_headers
    )

    assert response.status_code == 204, response.text

    _, response = await sanic_client.get("/api/secret/secrets", headers=user_headers)

    assert response.status_code == 200, response.text
    assert response.json is not None
    assert {s["name"] for s in response.json} == {"secret-1", "secret-3"}


@pytest.mark.asyncio
async def test_get_update_a_secret(
    sanic_client: SanicASGITestClient, user_headers, create_secret
):
    await create_secret("secret-1", "value-1")
    secret = await create_secret("secret-2", "value-2")
    await create_secret("secret-3", "value-3")

    secret_id = secret["id"]
    payload = {"name": "new-name", "value": "new-value"}

    _, response = await sanic_client.patch(
        f"/api/secret/secrets/{secret_id}", headers=user_headers, json=payload
    )

    assert response.status_code == 200, response.text

    _, response = await sanic_client.get(
        f"/api/secret/secrets/{secret_id}", headers=user_headers
    )

    assert response.status_code == 200, response.text
    assert response.json is not None
    assert response.json["name"] == "new-name"
    assert response.json["value"] == "new-value"
    assert response.json["id"] == secret_id


@pytest.mark.asyncio
async def test_cannot_get_another_user_secret(
    sanic_client: SanicASGITestClient, user_headers, admin_headers, create_secret
):
    await create_secret("secret-1", "value-1")
    secret = await create_secret("secret-2", "value-2")
    await create_secret("secret-3", "value-3")

    secret_id = secret["id"]

    _, response = await sanic_client.get(
        f"/api/secret/secrets/{secret_id}", headers=admin_headers
    )

    assert response.status_code == 404, response.text
    assert (
        "does not exist or you do not have access to it."
        in response.json["error"]["message"]
    )

    _, response = await sanic_client.get("/api/secret/secrets", headers=admin_headers)

    assert response.status_code == 200, response.text
    assert response.json == []


@pytest.mark.asyncio
async def test_anonymous_users_cannot_create_secrets(
    sanic_client: SanicASGITestClient, unauthorized_headers
):
    payload = {
        "name": "my-secret",
        "value": "42",
    }
    _, response = await sanic_client.post(
        "/api/secret/secrets", headers=unauthorized_headers, json=payload
    )

    assert response.status_code == 401, response.text
    assert (
        "You have to be authenticated to perform this operation."
        in response.json["error"]["message"]
    )
