"""Tests for secrets blueprints."""

from base64 import b64decode
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from sanic_testing.testing import SanicASGITestClient

from renku_data_services.base_models.core import InternalServiceAdmin, ServiceAdminId
from renku_data_services.secrets.core import rotate_encryption_keys, rotate_single_encryption_key
from renku_data_services.secrets.models import Secret, SecretKind
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
    async def create_secret_helper(name: str, value: str, kind: str = "general") -> dict[str, Any]:
        payload = {"name": name, "value": value, "kind": kind}

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
    assert response.json.keys() == {"name", "id", "modification_date", "kind"}
    assert response.json["name"] == "my-secret"
    assert response.json["id"] is not None
    assert response.json["modification_date"] is not None
    assert response.json["kind"] == kind


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
    await create_secret("secret-4", "value-4", kind="storage")

    _, response = await sanic_client.get("/api/data/user/secrets", headers=user_headers)

    assert response.status_code == 200, response.text
    assert response.json is not None
    assert {s["name"] for s in response.json} == {"secret-1", "secret-2", "secret-3"}


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
            }
        ],
    }

    _, response = await secrets_sanic_client.post("/api/secrets/kubernetes", headers=user_headers, json=payload)
    assert response.status_code == 201
    assert "test-secret" in secrets_storage_app_config.core_client.secrets
    k8s_secret = secrets_storage_app_config.core_client.secrets["test-secret"].data
    assert k8s_secret.keys() == {"secret-1", "secret-2"}

    _, response = await sanic_client.get("/api/data/user/secret_key", headers=user_headers)
    assert response.status_code == 200
    assert "secret_key" in response.json
    secret_key = response.json["secret_key"]

    assert decrypt_string(secret_key.encode(), "user", b64decode(k8s_secret["secret-1"])) == "value-1"
    assert decrypt_string(secret_key.encode(), "user", b64decode(k8s_secret["secret-2"])) == "value-2"


@pytest.mark.asyncio
async def test_secret_encryption_decryption_with_key_mapping(
    sanic_client: SanicASGITestClient,
    secrets_sanic_client: SanicASGITestClient,
    secrets_storage_app_config,
    user_headers,
    create_secret,
) -> None:
    """Test adding a secret and decrypting it in the secret service with mapping for key names."""
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
            }
        ],
        "key_mapping": {
            secret1_id: "access_key_id",
            secret2_id: "secret_access_key",
        },
    }

    _, response = await secrets_sanic_client.post("/api/secrets/kubernetes", headers=user_headers, json=payload)
    assert response.status_code == 201
    assert "test-secret" in secrets_storage_app_config.core_client.secrets
    k8s_secret = secrets_storage_app_config.core_client.secrets["test-secret"].data
    assert k8s_secret.keys() == {"access_key_id", "secret_access_key"}

    _, response = await sanic_client.get("/api/data/user/secret_key", headers=user_headers)
    assert response.status_code == 200
    assert "secret_key" in response.json
    secret_key = response.json["secret_key"]

    assert decrypt_string(secret_key.encode(), "user", b64decode(k8s_secret["access_key_id"])) == "value-1"
    assert decrypt_string(secret_key.encode(), "user", b64decode(k8s_secret["secret_access_key"])) == "value-2"

    # NOTE: Test missing secret_id in key mapping
    payload["key_mapping"] = {secret1_id: "access_key_id"}

    _, response = await secrets_sanic_client.post("/api/secrets/kubernetes", headers=user_headers, json=payload)

    assert response.status_code == 422
    assert response.json["error"]["message"] == "Key mapping must include all requested secret IDs"

    # NOTE: Test duplicated key mapping
    payload["key_mapping"] = {secret1_id: "access_key_id", secret2_id: "access_key_id"}

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
        name="test_secret", encrypted_value=encrypted_value, encrypted_key=encrypted_key, kind=SecretKind.general
    )

    rotated_secret = await rotate_single_encryption_key(secret, user_id, new_key, old_key)

    assert rotated_secret is not None
    with pytest.raises(ValueError):
        decrypt_rsa(old_key, rotated_secret.encrypted_key)

    new_encryption_key = decrypt_rsa(new_key, rotated_secret.encrypted_key)
    assert new_encryption_key != encryption_key
    decrypted_value = decrypt_string(new_encryption_key, user_id, rotated_secret.encrypted_value).encode()  # type: ignore
    assert decrypted_value.decode() == user_secret

    # ensure that rotating again does nothing

    result = await rotate_single_encryption_key(rotated_secret, user_id, new_key, old_key)
    assert result is None


@pytest.mark.asyncio
async def test_secret_rotation(sanic_client, secrets_storage_app_config, create_secret, user_headers, users):
    """Test rotating multiple secrets."""

    for i in range(10):
        await create_secret(f"secret-{i}", str(i))

    new_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    admin = InternalServiceAdmin(id=ServiceAdminId.secrets_rotation)
    await rotate_encryption_keys(
        admin,
        new_key,
        secrets_storage_app_config.secrets_service_private_key,
        secrets_storage_app_config.user_secrets_repo,
        batch_size=5,
    )

    secrets = [s async for s in secrets_storage_app_config.user_secrets_repo.get_all_secrets_batched(admin, 100)]
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
