"""Tests for secrets blueprints."""

import json
from base64 import b64decode
from typing import Any

import pytest
from sanic_testing.testing import SanicASGITestClient

from renku_data_services.utils.cryptography import decrypt_string


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

        _, response = await sanic_client.post("/api/data/user/secrets", headers=user_headers, json=payload)

        assert response.status_code == 201, response.text
        return response.json

    return create_secret_helper


@pytest.mark.asyncio
async def test_create_secrets(sanic_client: SanicASGITestClient, user_headers) -> None:
    payload = {
        "name": "my-secret",
        "value": "42",
    }
    _, response = await sanic_client.post("/api/data/user/secrets", headers=user_headers, json=payload)

    assert response.status_code == 201, response.text
    assert response.json is not None
    assert response.json["name"] == "my-secret"
    assert response.json["id"] is not None
    assert response.json["modification_date"] is not None


@pytest.mark.asyncio
async def test_get_one_secret(sanic_client: SanicASGITestClient, user_headers, create_secret) -> None:
    await create_secret("secret-1", "value-1")
    secret = await create_secret("secret-2", "value-2")
    await create_secret("secret-3", "value-3")

    secret_id = secret["id"]

    _, response = await sanic_client.get(f"/api/data/user/secrets/{secret_id}", headers=user_headers)

    assert response.status_code == 200, response.text
    assert response.json is not None
    assert response.json["name"] == "secret-2"
    assert response.json["id"] == secret_id
    assert "value" not in response.json


@pytest.mark.asyncio
async def test_get_all_secrets(sanic_client: SanicASGITestClient, user_headers, create_secret) -> None:
    await create_secret("secret-1", "value-1")
    await create_secret("secret-2", "value-2")
    await create_secret("secret-3", "value-3")

    _, response = await sanic_client.get("/api/data/user/secrets", headers=user_headers)

    assert response.status_code == 200, response.text
    assert response.json is not None
    assert {s["name"] for s in response.json} == {"secret-1", "secret-2", "secret-3"}


@pytest.mark.asyncio
async def test_get_delete_a_secret(sanic_client: SanicASGITestClient, user_headers, create_secret) -> None:
    await create_secret("secret-1", "value-1")
    secret = await create_secret("secret-2", "value-2")
    await create_secret("secret-3", "value-3")

    secret_id = secret["id"]

    _, response = await sanic_client.delete(f"/api/data/user/secrets/{secret_id}", headers=user_headers)

    assert response.status_code == 204, response.text

    _, response = await sanic_client.get("/api/data/user/secrets", headers=user_headers)

    assert response.status_code == 200, response.text
    assert response.json is not None
    assert {s["name"] for s in response.json} == {"secret-1", "secret-3"}


@pytest.mark.asyncio
async def test_get_update_a_secret(sanic_client: SanicASGITestClient, user_headers, create_secret) -> None:
    await create_secret("secret-1", "value-1")
    secret = await create_secret("secret-2", "value-2")
    await create_secret("secret-3", "value-3")

    secret_id = secret["id"]
    payload = {"value": "new-value"}

    _, response = await sanic_client.patch(f"/api/data/user/secrets/{secret_id}", headers=user_headers, json=payload)

    assert response.status_code == 200, response.text

    _, response = await sanic_client.get(f"/api/data/user/secrets/{secret_id}", headers=user_headers)

    assert response.status_code == 200, response.text
    assert response.json is not None
    assert response.json["id"] == secret_id
    assert "value" not in response.json


@pytest.mark.asyncio
async def test_cannot_get_another_user_secret(
    sanic_client: SanicASGITestClient, user_headers, admin_headers, create_secret
) -> None:
    await create_secret("secret-1", "value-1")
    secret = await create_secret("secret-2", "value-2")
    await create_secret("secret-3", "value-3")

    secret_id = secret["id"]

    _, response = await sanic_client.get(f"/api/data/user/secrets/{secret_id}", headers=admin_headers)

    assert response.status_code == 404, response.text
    assert "cannot be found" in response.json["error"]["message"]

    _, response = await sanic_client.get("/api/data/user/secrets", headers=admin_headers)

    assert response.status_code == 200, response.text
    assert response.json == []


@pytest.mark.asyncio
async def test_anonymous_users_cannot_create_secrets(sanic_client: SanicASGITestClient, unauthorized_headers) -> None:
    payload = {
        "name": "my-secret",
        "value": "42",
    }
    _, response = await sanic_client.post("/api/data/user/secrets", headers=unauthorized_headers, json=payload)

    assert response.status_code == 401, response.text
    assert "You have to be authenticated to perform this operation." in response.json["error"]["message"]


@pytest.mark.asyncio
async def test_secret_encryption_decryption(
    sanic_client: SanicASGITestClient,
    secrets_sanic_client: SanicASGITestClient,
    secrets_storage_app_config,
    user_headers,
    create_secret,
) -> None:
    """Test adding a secret and decrypting it in the secret service."""
    secret1 = await create_secret("secret-1", "value-1")
    secret1_id = secret1["id"]
    secret2 = await create_secret("secret-2", "value-2")
    secret2_id = secret2["id"]

    payload = {
        "name": "test-secret",
        "namespace": "test-namespace",
        "secret_ids": [secret1_id, secret2_id],
        "owner_references": [
            {
                "apiVersion": "amalthea.dev/v1alpha1",
                "kind": "JupyterServer",
                "name": "renku-1234",
                "uid": "c9328118-8d32-41b4-b9bd-1437880c95a2",
                "controller": True,
            }
        ],
    }

    _, response = await secrets_sanic_client.post("/api/secrets/kubernetes", headers=user_headers, json=payload)
    assert response.status_code == 201
    assert "test-secret" in secrets_storage_app_config.core_client.secrets
    k8s_secret = secrets_storage_app_config.core_client.secrets["test-secret"].data

    _, response = await sanic_client.get("/api/data/user/secret_key", headers=user_headers)
    assert response.status_code == 200
    assert "secret_key" in response.json
    secret_key = response.json["secret_key"]

    assert decrypt_string(secret_key.encode(), "user", b64decode(k8s_secret["secret-1"])) == "value-1"
    assert decrypt_string(secret_key.encode(), "user", b64decode(k8s_secret["secret-2"])) == "value-2"
