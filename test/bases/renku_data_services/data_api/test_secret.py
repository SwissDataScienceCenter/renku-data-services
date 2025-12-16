"""Tests for secrets blueprints."""

import time
from base64 import b64decode
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from sanic_testing.testing import SanicASGITestClient
from ulid import ULID

from renku_data_services.base_models.core import InternalServiceAdmin, ServiceAdminId
from renku_data_services.k8s.models import K8sSecret
from renku_data_services.secrets.models import Secret, SecretKind
from renku_data_services.secrets_storage_api.dependencies import DependencyManager
from renku_data_services.users import apispec
from renku_data_services.utils.cryptography import (
    decrypt_rsa,
    decrypt_string,
    encrypt_rsa,
    encrypt_string,
    generate_random_encryption_key,
)


@pytest.fixture
def create_secret(sanic_client: SanicASGITestClient, user_headers):
    async def create_secret_helper(
        name: str,
        value: str,
        kind: str = "general",
        expiration_timestamp: str = None,
        default_filename: str | None = None,
    ) -> dict[str, Any]:
        payload = {"name": name, "value": value, "kind": kind, "expiration_timestamp": expiration_timestamp}
        if default_filename:
            payload["default_filename"] = default_filename

        _, response = await sanic_client.post("/api/data/user/secrets", headers=user_headers, json=payload)

        assert response.status_code == 201, response.text
        return response.json

    return create_secret_helper


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", [e.value for e in apispec.SecretKind])
async def test_create_secrets(sanic_client: SanicASGITestClient, user_headers, kind) -> None:
    payload = {
        "name": "my-secret",
        "value": "42",
        "kind": kind,
    }
    _, response = await sanic_client.post("/api/data/user/secrets", headers=user_headers, json=payload)

    assert response.status_code == 201, response.text
    assert response.json is not None
    assert response.json.keys() == {
        "id",
        "name",
        "kind",
        "expiration_timestamp",
        "modification_date",
        "default_filename",
        "session_secret_slot_ids",
        "data_connector_ids",
    }
    assert response.json["id"] is not None
    assert response.json["name"] == "my-secret"
    assert response.json["kind"] == kind
    assert response.json["expiration_timestamp"] is None
    assert response.json["modification_date"] is not None
    assert response.json["default_filename"] is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", [e.value for e in apispec.SecretKind])
async def test_create_secrets_with_expiration_timestamps(sanic_client: SanicASGITestClient, user_headers, kind) -> None:
    payload = {
        "name": "my-secret-that-expires",
        "value": "42",
        "kind": kind,
        "expiration_timestamp": "2029-12-31T23:59:59+01:00",
    }
    _, response = await sanic_client.post("/api/data/user/secrets", headers=user_headers, json=payload)
    assert response.status_code == 201, response.text
    assert response.json is not None
    assert response.json.keys() == {
        "id",
        "name",
        "kind",
        "expiration_timestamp",
        "modification_date",
        "default_filename",
        "session_secret_slot_ids",
        "data_connector_ids",
    }
    assert response.json["name"] == "my-secret-that-expires"
    assert response.json["id"] is not None
    assert response.json["kind"] == kind
    assert response.json["expiration_timestamp"] == "2029-12-31T23:59:59+01:00"
    assert response.json["modification_date"] is not None


@pytest.mark.asyncio
async def test_get_one_secret(sanic_client: SanicASGITestClient, user_headers, create_secret) -> None:
    await create_secret("secret-1", "value-1")
    secret = await create_secret("secret-2", "value-2")
    await create_secret("secret-3", "value-3")

    _, response = await sanic_client.get(f"/api/data/user/secrets/{secret["id"]}", headers=user_headers)
    assert response.status_code == 200, response.text
    assert response.json is not None
    assert response.json["name"] == secret["name"]
    assert response.json["id"] == secret["id"]
    assert "value" not in response.json


@pytest.mark.asyncio
async def test_get_one_secret_not_expired(sanic_client: SanicASGITestClient, user_headers, create_secret) -> None:
    expiration_timestamp = (datetime.now(ZoneInfo("Europe/Berlin")) + timedelta(seconds=(120 + 15))).isoformat()
    secret_1 = await create_secret("secret-1", "value-1", expiration_timestamp=expiration_timestamp)
    secret_2 = await create_secret("secret-2", "value-2", expiration_timestamp="2029-12-31T23:59:59+01:00")

    _, response = await sanic_client.get(f"/api/data/user/secrets/{secret_1["id"]}", headers=user_headers)
    assert response.status_code == 200, response.text
    assert response.json is not None
    assert response.json["name"] == "secret-1"
    assert response.json["id"] == secret_1["id"]

    _, response = await sanic_client.get(f"/api/data/user/secrets/{secret_2["id"]}", headers=user_headers)
    assert response.status_code == 200, response.text
    assert response.json is not None
    assert response.json["name"] == "secret-2"
    assert response.json["id"] == secret_2["id"]

    time.sleep(20)

    _, response = await sanic_client.get(f"/api/data/user/secrets/{secret_1["id"]}", headers=user_headers)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_all_secrets(sanic_client: SanicASGITestClient, user_headers, create_secret) -> None:
    await create_secret("secret-1", "value-1")
    await create_secret("secret-2", "value-2")
    await create_secret("secret-3", "value-3")
    await create_secret("secret-4", "value-4", kind="storage")

    _, response = await sanic_client.get("/api/data/user/secrets", headers=user_headers)

    assert response.status_code == 200, response.text
    assert response.json is not None
    assert {s["name"] for s in response.json} == {"secret-1", "secret-2", "secret-3"}


@pytest.mark.asyncio
async def test_get_all_secrets_not_expired(sanic_client: SanicASGITestClient, user_headers, create_secret) -> None:
    expiration_timestamp = (datetime.now(ZoneInfo("Europe/Berlin")) + timedelta(seconds=10)).isoformat()
    await create_secret("secret-1", "value-1", expiration_timestamp=expiration_timestamp)
    await create_secret("secret-2", "value-2")
    await create_secret("secret-3", "value-3", expiration_timestamp="2029-12-31T23:59:59+01:00")

    time.sleep(15)

    _, response = await sanic_client.get("/api/data/user/secrets", headers=user_headers)
    assert response.status_code == 200, response.text
    assert response.json is not None
    assert {s["name"] for s in response.json} == {"secret-2", "secret-3"}
    assert {s["expiration_timestamp"] for s in response.json if s["name"] == "secret-3"} == {"2029-12-31T22:59:59Z"}


@pytest.mark.asyncio
async def test_get_all_secrets_filtered_by_kind(sanic_client, user_headers, create_secret) -> None:
    await create_secret("secret-1", "value-1")
    await create_secret("secret-2", "value-2", kind="storage")
    await create_secret("secret-3", "value-3")
    await create_secret("secret-4", "value-4", kind="storage")

    # NOTE: By default, only `general` secrets are returned
    _, response = await sanic_client.get("/api/data/user/secrets", headers=user_headers)

    assert response.status_code == 200, response.text
    assert {s["name"] for s in response.json} == {"secret-1", "secret-3"}

    _, response = await sanic_client.get("/api/data/user/secrets", params={"kind": "general"}, headers=user_headers)

    assert response.status_code == 200, response.text
    assert {s["name"] for s in response.json} == {"secret-1", "secret-3"}

    _, response = await sanic_client.get("/api/data/user/secrets", params={"kind": "storage"}, headers=user_headers)

    assert response.status_code == 200, response.text
    assert {s["name"] for s in response.json} == {"secret-2", "secret-4"}


@pytest.mark.asyncio
async def test_get_delete_a_secret(sanic_client: SanicASGITestClient, user_headers, create_secret) -> None:
    await create_secret("secret-1", "value-1")
    secret = await create_secret("secret-2", "value-2")
    await create_secret("secret-3", "value-3")

    _, response = await sanic_client.delete(f"/api/data/user/secrets/{secret["id"]}", headers=user_headers)
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

    _, response = await sanic_client.patch(
        f"/api/data/user/secrets/{secret["id"]}", headers=user_headers, json={"name": "secret-2", "value": "new-value"}
    )
    assert response.status_code == 200, response.text
    assert response.json is not None
    assert response.json["id"] == secret["id"]
    assert response.json["name"] == secret["name"]
    assert response.json["expiration_timestamp"] is None
    assert "value" not in response.json

    _, response = await sanic_client.get(f"/api/data/user/secrets/{secret["id"]}", headers=user_headers)
    assert response.status_code == 200, response.text
    assert response.json is not None
    assert response.json["id"] == secret["id"]
    assert response.json["name"] == secret["name"]
    assert response.json["expiration_timestamp"] is None
    assert "value" not in response.json

    _, response = await sanic_client.patch(
        f"/api/data/user/secrets/{secret["id"]}",
        headers=user_headers,
        json={"value": "newest-value", "expiration_timestamp": "2029-12-31T00:00:00Z"},
    )
    assert response.status_code == 200, response.text

    _, response = await sanic_client.get(f"/api/data/user/secrets/{secret["id"]}", headers=user_headers)
    assert response.status_code == 200, response.text
    assert response.json is not None
    assert response.json["id"] == secret["id"]
    assert response.json["name"] == secret["name"]
    assert response.json["expiration_timestamp"] == "2029-12-31T00:00:00Z"
    assert "value" not in response.json


@pytest.mark.asyncio
async def test_cannot_get_another_user_secret(
    sanic_client: SanicASGITestClient, user_headers, admin_headers, create_secret
) -> None:
    await create_secret("secret-1", "value-1")
    secret = await create_secret("secret-2", "value-2")
    await create_secret("secret-3", "value-3")

    _, response = await sanic_client.get(f"/api/data/user/secrets/{secret["id"]}", headers=admin_headers)
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
    secrets_storage_app_manager,
    user_headers,
    create_secret,
) -> None:
    """Test adding a secret and decrypting it in the secret service."""
    secret1 = await create_secret("secret-1", "value-1", default_filename="secret-1")
    secret1_id = secret1["id"]
    secret2 = await create_secret("secret-2", "value-2", default_filename="secret-2")
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
            }
        ],
    }

    _, response = await secrets_sanic_client.post("/api/secrets/kubernetes", headers=user_headers, json=payload)
    assert response.status_code == 201
    assert "test-secret" in secrets_storage_app_manager.secret_client.secrets
    k8s_secret: K8sSecret = secrets_storage_app_manager.secret_client.secrets["test-secret"]
    secrets = k8s_secret.manifest.get("data", {})

    assert secrets.keys() == {"secret-1", "secret-2"}

    _, response = await sanic_client.get("/api/data/user/secret_key", headers=user_headers)
    assert response.status_code == 200
    assert "secret_key" in response.json
    secret_key = response.json["secret_key"]

    assert decrypt_string(secret_key.encode(), "user", b64decode(secrets["secret-1"])) == "value-1"
    assert decrypt_string(secret_key.encode(), "user", b64decode(secrets["secret-2"])) == "value-2"


@pytest.mark.asyncio
async def test_secret_encryption_decryption_with_key_mapping(
    sanic_client: SanicASGITestClient,
    secrets_sanic_client: SanicASGITestClient,
    secrets_storage_app_manager,
    user_headers,
    create_secret,
) -> None:
    """Test adding a secret and decrypting it in the secret service with mapping for key names."""
    secret1 = await create_secret("secret-1", "value-1")
    secret1_id = secret1["id"]
    secret2 = await create_secret("secret-2", "value-2")
    secret2_id = secret2["id"]
    secret3 = await create_secret("secret-3", "value-3")
    secret3_id = secret3["id"]

    payload = {
        "name": "test-secret",
        "namespace": "test-namespace",
        "secret_ids": [secret1_id, secret2_id, secret3_id],
        "owner_references": [
            {
                "apiVersion": "amalthea.dev/v1alpha1",
                "kind": "JupyterServer",
                "name": "renku-1234",
                "uid": "c9328118-8d32-41b4-b9bd-1437880c95a2",
            }
        ],
        "key_mapping": {
            secret1_id: "access_key_id",
            secret2_id: "secret_access_key",
            secret3_id: ["secret-3-one", "secret-3-two"],
        },
    }

    _, response = await secrets_sanic_client.post("/api/secrets/kubernetes", headers=user_headers, json=payload)
    assert response.status_code == 201
    assert "test-secret" in secrets_storage_app_manager.secret_client.secrets
    k8s_secret: K8sSecret = secrets_storage_app_manager.secret_client.secrets["test-secret"]
    secrets = k8s_secret.manifest.get("data", {})
    assert secrets.keys() == {"access_key_id", "secret_access_key", "secret-3-one", "secret-3-two"}

    _, response = await sanic_client.get("/api/data/user/secret_key", headers=user_headers)
    assert response.status_code == 200
    assert "secret_key" in response.json
    secret_key = response.json["secret_key"]

    assert decrypt_string(secret_key.encode(), "user", b64decode(secrets["access_key_id"])) == "value-1"
    assert decrypt_string(secret_key.encode(), "user", b64decode(secrets["secret_access_key"])) == "value-2"
    assert decrypt_string(secret_key.encode(), "user", b64decode(secrets["secret-3-one"])) == "value-3"
    assert decrypt_string(secret_key.encode(), "user", b64decode(secrets["secret-3-two"])) == "value-3"

    # NOTE: Test missing secret_id in key mapping
    payload["key_mapping"] = {secret1_id: "access_key_id"}

    _, response = await secrets_sanic_client.post("/api/secrets/kubernetes", headers=user_headers, json=payload)

    assert response.status_code == 422
    assert response.json["error"]["message"] == "Key mapping must include all requested secret IDs"

    # NOTE: Test duplicated key mapping
    payload["key_mapping"] = {secret1_id: "access_key_id", secret2_id: "access_key_id", secret3_id: "secret-3"}

    _, response = await secrets_sanic_client.post("/api/secrets/kubernetes", headers=user_headers, json=payload)

    assert response.status_code == 422
    assert response.json["error"]["message"] == "Key mapping values are not unique"


@pytest.mark.asyncio
async def test_single_secret_rotation():
    """Test rotating secrets."""
    old_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    new_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    encryption_key = generate_random_encryption_key()
    user_id = "123456"

    user_secret = "abcdefg"

    encrypted_value = encrypt_string(encryption_key, user_id, user_secret)
    encrypted_key = encrypt_rsa(old_key.public_key(), encryption_key)

    secret = Secret(
        id=ULID(),
        name="My secret",
        default_filename="test_secret",
        encrypted_value=encrypted_value,
        encrypted_key=encrypted_key,
        kind=SecretKind.general,
        modification_date=datetime.now(tz=UTC),
        session_secret_slot_ids=[],
        data_connector_ids=[],
    )

    rotated_secret = await secret.rotate_single_encryption_key(user_id, new_key, old_key)

    assert rotated_secret is not None
    with pytest.raises(ValueError):
        decrypt_rsa(old_key, rotated_secret.encrypted_key)

    new_encryption_key = decrypt_rsa(new_key, rotated_secret.encrypted_key)
    assert new_encryption_key != encryption_key
    decrypted_value = decrypt_string(new_encryption_key, user_id, rotated_secret.encrypted_value).encode()  # type: ignore
    assert decrypted_value.decode() == user_secret

    # ensure that rotating again does nothing

    result = await rotated_secret.rotate_single_encryption_key(user_id, new_key, old_key)
    assert result is None


@pytest.mark.asyncio
async def test_secret_rotation(
    sanic_client, secrets_storage_app_manager: DependencyManager, create_secret, user_headers, users
):
    """Test rotating multiple secrets."""

    for i in range(10):
        await create_secret(f"secret-{i}", str(i))

    new_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    admin = InternalServiceAdmin(id=ServiceAdminId.secrets_rotation)
    await secrets_storage_app_manager.user_secrets_repo.rotate_encryption_keys(
        admin,
        new_key,
        secrets_storage_app_manager.config.secrets.private_key,
        batch_size=5,
    )

    secrets = [s async for s in secrets_storage_app_manager.user_secrets_repo.get_all_secrets_batched(admin, 100)]
    batch = secrets[0]
    assert len(batch) == 10

    _, response = await sanic_client.get("/api/data/user/secret_key", headers=user_headers)
    assert response.status_code == 200
    assert "secret_key" in response.json
    secret_key = response.json["secret_key"]

    for secret, _ in batch:
        new_encryption_key = decrypt_rsa(new_key, secret.encrypted_key)
        decrypted_value = decrypt_string(new_encryption_key, users[1].id, secret.encrypted_value).encode()  # type: ignore
        decrypted_value = decrypt_string(secret_key.encode(), users[1].id, decrypted_value)
        assert f"secret-{decrypted_value}" == secret.name


@pytest.mark.asyncio
async def test_patch_user_secret(sanic_client: SanicASGITestClient, user_headers, create_secret) -> None:
    secret = await create_secret("a-secret", "value-2")
    secret_id = secret["id"]

    payload = {"name": "A very important secret", "default_filename": "my-secret.txt"}

    _, response = await sanic_client.patch(f"/api/data/user/secrets/{secret_id}", headers=user_headers, json=payload)

    assert response.status_code == 200, response.text

    _, response = await sanic_client.get(f"/api/data/user/secrets/{secret_id}", headers=user_headers)

    assert response.status_code == 200, response.text
    assert response.json is not None
    assert response.json["id"] == secret_id
    assert "value" not in response.json
    assert response.json.get("name") == "A very important secret"
    assert response.json.get("default_filename") == "my-secret.txt"
