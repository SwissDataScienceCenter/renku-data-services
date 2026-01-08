"""Tests for session secrets blueprint."""

from typing import Any

import pytest
import pytest_asyncio
from sanic_testing.testing import SanicASGITestClient
from ulid import ULID

from renku_data_services.users.models import UserInfo
from test.bases.renku_data_services.data_api.utils import merge_headers


@pytest_asyncio.fixture
async def create_session_secret_slot(sanic_client: SanicASGITestClient, regular_user: UserInfo, user_headers):
    async def create_session_secret_slot_helper(
        project_id: str, filename: str, user: UserInfo | None = None, headers: dict[str, str] | None = None, **payload
    ) -> dict[str, Any]:
        user = user or regular_user
        headers = headers or user_headers
        secret_slot_payload = {"project_id": project_id, "filename": filename, "description": "A secret slot"}
        secret_slot_payload.update(payload)

        _, response = await sanic_client.post(
            "/api/data/session_secret_slots", headers=headers, json=secret_slot_payload
        )

        assert response.status_code == 201, response.text
        return response.json

    return create_session_secret_slot_helper


@pytest.mark.asyncio
async def test_post_session_secret_slot(sanic_client: SanicASGITestClient, create_project, user_headers) -> None:
    project = await create_project(sanic_client, "My project")
    project_id = project["id"]

    payload = {
        "project_id": project_id,
        "filename": "test_secret",
        "name": "My secret",
        "description": "This is a secret slot.",
    }
    _, response = await sanic_client.post("/api/data/session_secret_slots", headers=user_headers, json=payload)

    assert response.status_code == 201, response.text
    assert response.json is not None
    secret_slot = response.json
    assert secret_slot.get("filename") == "test_secret"
    assert secret_slot.get("name") == "My secret"
    assert secret_slot.get("description") == "This is a secret slot."


@pytest.mark.asyncio
async def test_post_session_secret_slot_with_minimal_payload(
    sanic_client: SanicASGITestClient, create_project, user_headers
) -> None:
    project = await create_project(sanic_client, "My project")
    project_id = project["id"]

    payload = {
        "project_id": project_id,
        "filename": "test_secret",
    }
    _, response = await sanic_client.post("/api/data/session_secret_slots", headers=user_headers, json=payload)

    assert response.status_code == 201, response.text
    assert response.json is not None
    secret_slot = response.json
    assert secret_slot.get("filename") == "test_secret"
    assert secret_slot.get("name") == "test_secret"
    assert secret_slot.get("description") is None


@pytest.mark.asyncio
async def test_post_session_secret_slot_with_invalid_project_id(
    sanic_client: SanicASGITestClient, create_project, user_headers
) -> None:
    project_id = str(ULID())

    payload = {
        "project_id": project_id,
        "filename": "test_secret",
        "name": "My secret",
        "description": "This is a secret slot.",
    }
    _, response = await sanic_client.post("/api/data/session_secret_slots", headers=user_headers, json=payload)

    assert response.status_code == 404, response.text


@pytest.mark.asyncio
async def test_post_session_secret_slot_with_unauthorized_project(
    sanic_client: SanicASGITestClient, create_project, user_headers
) -> None:
    project = await create_project(sanic_client, "My project", admin=True)
    project_id = project["id"]

    payload = {
        "project_id": project_id,
        "filename": "test_secret",
        "name": "My secret",
        "description": "This is a secret slot.",
    }
    _, response = await sanic_client.post("/api/data/session_secret_slots", headers=user_headers, json=payload)

    assert response.status_code == 404, response.text


@pytest.mark.asyncio
async def test_post_session_secret_slot_with_invalid_filename(
    sanic_client: SanicASGITestClient, create_project, user_headers
) -> None:
    project = await create_project(sanic_client, "My project")
    project_id = project["id"]

    payload = {
        "project_id": project_id,
        "filename": "test/secret",
    }
    _, response = await sanic_client.post("/api/data/session_secret_slots", headers=user_headers, json=payload)

    assert response.status_code == 422, response.text
    assert "filename: String should match pattern" in response.json["error"]["message"]


@pytest.mark.asyncio
async def test_post_session_secret_slot_with_conflicting_filename(
    sanic_client: SanicASGITestClient, create_project, user_headers
) -> None:
    project = await create_project(sanic_client, "My project")
    project_id = project["id"]
    payload = {
        "project_id": project_id,
        "name": "Existing secret",
        "filename": "test_secret",
    }
    _, response = await sanic_client.post("/api/data/session_secret_slots", headers=user_headers, json=payload)
    assert response.status_code == 201, response.text

    payload = {
        "project_id": project_id,
        "filename": "test_secret",
    }
    _, response = await sanic_client.post("/api/data/session_secret_slots", headers=user_headers, json=payload)

    assert response.status_code == 409, response.text


@pytest.mark.asyncio
async def test_get_project_session_secret_slots(
    sanic_client: SanicASGITestClient, create_project, create_session_secret_slot, user_headers
) -> None:
    project = await create_project(sanic_client, "My project")
    project_id = project["id"]

    for i in range(1, 10):
        await create_session_secret_slot(project_id, f"secret_slot_{i}")

    _, response = await sanic_client.get(f"/api/data/projects/{project_id}/session_secret_slots", headers=user_headers)

    assert response.status_code == 200, response.text
    assert response.json is not None
    secret_slots = response.json
    assert {secret_slot["filename"] for secret_slot in secret_slots} == {f"secret_slot_{i}" for i in range(1, 10)}


@pytest.mark.asyncio
async def test_get_one_session_secret_slot(
    sanic_client: SanicASGITestClient, create_project, create_session_secret_slot, user_headers
) -> None:
    project = await create_project(sanic_client, "My project")
    project_id = project["id"]
    secret_slot = await create_session_secret_slot(project_id, "test_secret")
    secret_slot_id = secret_slot["id"]

    _, response = await sanic_client.get(f"/api/data/session_secret_slots/{secret_slot_id}", headers=user_headers)

    assert response.status_code == 200, response.text
    assert response.json is not None
    secret_slot = response.json
    assert secret_slot.keys() == {"id", "project_id", "name", "description", "filename", "etag"}
    assert secret_slot.get("id") == secret_slot_id
    assert secret_slot.get("project_id") == project_id
    assert secret_slot.get("filename") == "test_secret"
    assert secret_slot.get("name") == "test_secret"
    assert secret_slot.get("description") == "A secret slot"
    assert secret_slot.get("etag") is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("headers_name", ["unauthorized_headers", "member_1_headers"])
async def test_get_one_session_secret_slot_unauthorized(
    sanic_client: SanicASGITestClient,
    create_project,
    create_session_secret_slot,
    headers_name,
    request,
    unauthorized_headers,
    member_1_headers,
) -> None:
    project = await create_project(sanic_client, "My project")
    project_id = project["id"]
    secret_slot = await create_session_secret_slot(project_id, "test_secret")
    secret_slot_id = secret_slot["id"]

    headers = request.getfixturevalue(headers_name)
    _, response = await sanic_client.get(f"/api/data/session_secret_slots/{secret_slot_id}", headers=headers)

    assert response.status_code == 404, response.text


@pytest.mark.asyncio
async def test_patch_session_secret_slot(
    sanic_client: SanicASGITestClient, create_project, create_session_secret_slot, user_headers
) -> None:
    project = await create_project(sanic_client, "My project")
    project_id = project["id"]
    secret_slot = await create_session_secret_slot(project_id, "test_secret")
    secret_slot_id = secret_slot["id"]

    headers = merge_headers(user_headers, {"If-Match": secret_slot["etag"]})
    patch = {
        "name": "New Name",
        "description": "Updated session secret slot",
        "filename": "new_filename",
    }

    _, response = await sanic_client.patch(
        f"/api/data/session_secret_slots/{secret_slot_id}", headers=headers, json=patch
    )

    assert response.status_code == 200, response.text
    assert response.json is not None
    secret_slot = response.json
    assert secret_slot.get("id") == secret_slot_id
    assert secret_slot.get("project_id") == project_id
    assert secret_slot.get("filename") == "new_filename"
    assert secret_slot.get("name") == "New Name"
    assert secret_slot.get("description") == "Updated session secret slot"


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["id", "project_id"])
async def test_patch_session_secret_slot_reserved_fields_are_forbidden(
    sanic_client: SanicASGITestClient, create_project, create_session_secret_slot, user_headers, field
) -> None:
    project = await create_project(sanic_client, "My project")
    project_id = project["id"]
    secret_slot = await create_session_secret_slot(project_id, "test_secret")
    secret_slot_id = secret_slot["id"]
    original_value = secret_slot[field]

    headers = merge_headers(user_headers, {"If-Match": secret_slot["etag"]})
    patch = {
        field: "new-value",
    }
    _, response = await sanic_client.patch(
        f"/api/data/session_secret_slots/{secret_slot_id}", headers=headers, json=patch
    )

    assert response.status_code == 422, response.text
    assert f"{field}: Extra inputs are not permitted" in response.text

    # Check that the field's value didn't change
    _, response = await sanic_client.get(f"/api/data/session_secret_slots/{secret_slot_id}", headers=user_headers)
    assert response.status_code == 200, response.text
    secret_slot = response.json
    assert secret_slot[field] == original_value


@pytest.mark.asyncio
async def test_patch_session_secret_slot_without_if_match_header(
    sanic_client: SanicASGITestClient, create_project, create_session_secret_slot, user_headers
) -> None:
    project = await create_project(sanic_client, "My project")
    project_id = project["id"]
    secret_slot = await create_session_secret_slot(project_id, "test_secret")
    secret_slot_id = secret_slot["id"]
    original_value = secret_slot["name"]

    patch = {
        "name": "New Name",
    }
    _, response = await sanic_client.patch(
        f"/api/data/session_secret_slots/{secret_slot_id}", headers=user_headers, json=patch
    )

    assert response.status_code == 428, response.text
    assert "If-Match header not provided" in response.text

    # Check that the field's value didn't change
    _, response = await sanic_client.get(f"/api/data/session_secret_slots/{secret_slot_id}", headers=user_headers)
    assert response.status_code == 200, response.text
    data_connector = response.json
    assert data_connector["name"] == original_value


@pytest.mark.asyncio
async def test_patch_session_secret_slot_with_invalid_filename(
    sanic_client: SanicASGITestClient, create_project, create_session_secret_slot, user_headers
) -> None:
    project = await create_project(sanic_client, "My project")
    project_id = project["id"]
    secret_slot = await create_session_secret_slot(project_id, "test_secret")
    secret_slot_id = secret_slot["id"]
    original_value = secret_slot["name"]

    headers = merge_headers(user_headers, {"If-Match": secret_slot["etag"]})
    patch = {
        "filename": "test/secret",
    }
    _, response = await sanic_client.patch(
        f"/api/data/session_secret_slots/{secret_slot_id}", headers=headers, json=patch
    )

    assert response.status_code == 422, response.text
    assert "filename: String should match pattern" in response.json["error"]["message"]

    # Check that the field's value didn't change
    _, response = await sanic_client.get(f"/api/data/session_secret_slots/{secret_slot_id}", headers=user_headers)
    assert response.status_code == 200, response.text
    secret_slot = response.json
    assert secret_slot["filename"] == original_value


@pytest.mark.asyncio
async def test_patch_session_secret_slot_with_conflicting_filename(
    sanic_client: SanicASGITestClient, create_project, create_session_secret_slot, user_headers
) -> None:
    project = await create_project(sanic_client, "My project")
    project_id = project["id"]
    await create_session_secret_slot(project_id, "existing_filename")
    secret_slot = await create_session_secret_slot(project_id, "test_secret")
    secret_slot_id = secret_slot["id"]
    original_value = secret_slot["name"]

    headers = merge_headers(user_headers, {"If-Match": secret_slot["etag"]})
    patch = {
        "filename": "existing_filename",
    }
    _, response = await sanic_client.patch(
        f"/api/data/session_secret_slots/{secret_slot_id}", headers=headers, json=patch
    )

    assert response.status_code == 409, response.text

    # Check that the field's value didn't change
    _, response = await sanic_client.get(f"/api/data/session_secret_slots/{secret_slot_id}", headers=user_headers)
    assert response.status_code == 200, response.text
    secret_slot = response.json
    assert secret_slot["filename"] == original_value


@pytest.mark.asyncio
async def test_delete_session_secret_slot(
    sanic_client: SanicASGITestClient, create_project, create_session_secret_slot, user_headers
) -> None:
    project = await create_project(sanic_client, "My project")
    project_id = project["id"]
    await create_session_secret_slot(project_id, "test_secret_1")
    secret_slot = await create_session_secret_slot(project_id, "test_secret_2")
    await create_session_secret_slot(project_id, "test_secret_3")
    secret_slot_id = secret_slot["id"]

    _, response = await sanic_client.delete(f"/api/data/session_secret_slots/{secret_slot_id}", headers=user_headers)

    assert response.status_code == 204, response.text

    _, response = await sanic_client.get(f"/api/data/projects/{project_id}/session_secret_slots", headers=user_headers)

    assert response.status_code == 200, response.text
    assert {secret_slot["filename"] for secret_slot in response.json} == {"test_secret_1", "test_secret_3"}


@pytest.mark.asyncio
async def test_patch_session_secrets_with_existing_user_secret(
    sanic_client: SanicASGITestClient, create_project, create_session_secret_slot, user_headers
) -> None:
    project = await create_project(sanic_client, "My project")
    project_id = project["id"]
    secret_slot = await create_session_secret_slot(project_id, "test_secret")
    secret_slot_id = secret_slot["id"]
    payload = {"name": "my-user-secret", "value": "a secret value", "kind": "general"}
    _, response = await sanic_client.post("/api/data/user/secrets", headers=user_headers, json=payload)
    assert response.status_code == 201, response.text
    user_secret = response.json
    user_secret_id = user_secret["id"]

    patch = [{"secret_slot_id": secret_slot_id, "secret_id": user_secret_id}]
    _, response = await sanic_client.patch(
        f"/api/data/projects/{project_id}/session_secrets", headers=user_headers, json=patch
    )

    assert response.status_code == 200, response.text
    assert response.json is not None
    session_secrets = response.json
    assert len(session_secrets) == 1
    assert session_secrets[0].get("secret_slot") is not None
    assert session_secrets[0]["secret_slot"].get("id") == secret_slot_id
    assert session_secrets[0]["secret_slot"].get("name") == secret_slot["name"]
    assert session_secrets[0]["secret_slot"].get("filename") == secret_slot["filename"]
    assert session_secrets[0].get("secret_id") == user_secret_id

    # Check that the secrets are returned from a GET request
    _, response = await sanic_client.get(f"/api/data/projects/{project_id}/session_secrets", headers=user_headers)
    assert response.status_code == 200, response.json
    assert response.json is not None
    session_secrets = response.json
    assert len(session_secrets) == 1
    assert session_secrets[0].get("secret_slot") is not None
    assert session_secrets[0]["secret_slot"].get("id") == secret_slot_id
    assert session_secrets[0].get("secret_id") == user_secret_id

    # Check that the secret slot is referenced from the user secret
    _, response = await sanic_client.get(f"/api/data/user/secrets/{user_secret_id}", headers=user_headers)
    assert response.status_code == 200, response.json
    assert response.json is not None
    assert response.json.get("session_secret_slot_ids") is not None
    assert {id for id in response.json.get("session_secret_slot_ids")} == {secret_slot_id}


@pytest.mark.asyncio
async def test_patch_session_secrets_with_new_secret_value(
    sanic_client: SanicASGITestClient, create_project, create_session_secret_slot, user_headers
) -> None:
    project = await create_project(sanic_client, "My project")
    project_id = project["id"]
    secret_slot = await create_session_secret_slot(project_id, "test_secret")
    secret_slot_id = secret_slot["id"]

    patch = [{"secret_slot_id": secret_slot_id, "value": "a new secret value"}]
    _, response = await sanic_client.patch(
        f"/api/data/projects/{project_id}/session_secrets", headers=user_headers, json=patch
    )

    assert response.status_code == 200, response.text
    assert response.json is not None
    session_secrets = response.json
    assert len(session_secrets) == 1
    assert session_secrets[0].get("secret_slot") is not None
    assert session_secrets[0]["secret_slot"].get("id") == secret_slot_id
    assert session_secrets[0]["secret_slot"].get("name") == secret_slot["name"]
    assert session_secrets[0]["secret_slot"].get("filename") == secret_slot["filename"]
    assert session_secrets[0].get("secret_id") is not None

    # Check that the secrets are returned from a GET request
    _, response = await sanic_client.get("/api/data/user/secrets", headers=user_headers)
    assert response.status_code == 200, response.text
    user_secrets = response.json
    new_user_secret = user_secrets[0]
    _, response = await sanic_client.get(f"/api/data/projects/{project_id}/session_secrets", headers=user_headers)
    assert response.status_code == 200, response.json
    assert response.json is not None
    session_secrets = response.json
    assert len(session_secrets) == 1
    assert session_secrets[0].get("secret_slot") is not None
    assert session_secrets[0]["secret_slot"].get("id") == secret_slot_id
    assert session_secrets[0].get("secret_id") == new_user_secret["id"]

    # Check that the secret slot is referenced from the user secret
    _, response = await sanic_client.get(f"/api/data/user/secrets/{new_user_secret['id']}", headers=user_headers)
    assert response.status_code == 200, response.json
    assert response.json is not None
    assert response.json.get("session_secret_slot_ids") is not None
    assert {id for id in response.json.get("session_secret_slot_ids")} == {secret_slot_id}


@pytest.mark.asyncio
async def test_patch_session_secrets_update_with_another_user_secret(
    sanic_client: SanicASGITestClient, create_project, create_session_secret_slot, user_headers
) -> None:
    project = await create_project(sanic_client, "My project")
    project_id = project["id"]
    secret_slot = await create_session_secret_slot(project_id, "test_secret")
    secret_slot_id = secret_slot["id"]
    patch = [{"secret_slot_id": secret_slot_id, "value": "a new secret value"}]
    _, response = await sanic_client.patch(
        f"/api/data/projects/{project_id}/session_secrets", headers=user_headers, json=patch
    )
    assert response.status_code == 200, response.json
    session_secrets = response.json

    payload = {"name": "my-user-secret", "value": "another secret value", "kind": "general"}
    _, response = await sanic_client.post("/api/data/user/secrets", headers=user_headers, json=payload)
    assert response.status_code == 201, response.text
    replacement_user_secret = response.json
    replacement_user_secret_id = replacement_user_secret["id"]

    patch = [{"secret_slot_id": secret_slot_id, "secret_id": replacement_user_secret_id}]
    _, response = await sanic_client.patch(
        f"/api/data/projects/{project_id}/session_secrets", headers=user_headers, json=patch
    )

    assert response.status_code == 200, response.text
    assert response.json is not None
    session_secrets = response.json
    assert len(session_secrets) == 1
    assert session_secrets[0].get("secret_slot") is not None
    assert session_secrets[0]["secret_slot"].get("id") == secret_slot_id
    assert session_secrets[0]["secret_slot"].get("name") == secret_slot["name"]
    assert session_secrets[0]["secret_slot"].get("filename") == secret_slot["filename"]
    assert session_secrets[0].get("secret_id") == replacement_user_secret_id

    # Check that the secrets are returned from a GET request
    _, response = await sanic_client.get(f"/api/data/projects/{project_id}/session_secrets", headers=user_headers)
    assert response.status_code == 200, response.json
    assert response.json is not None
    session_secrets = response.json
    assert len(session_secrets) == 1
    assert session_secrets[0].get("secret_slot") is not None
    assert session_secrets[0]["secret_slot"].get("id") == secret_slot_id
    assert session_secrets[0].get("secret_id") == replacement_user_secret_id


@pytest.mark.asyncio
async def test_patch_session_secrets_update_with_a_new_secret_value(
    sanic_client: SanicASGITestClient, create_project, create_session_secret_slot, user_headers
) -> None:
    project = await create_project(sanic_client, "My project")
    project_id = project["id"]
    secret_slot = await create_session_secret_slot(project_id, "test_secret")
    secret_slot_id = secret_slot["id"]
    patch = [{"secret_slot_id": secret_slot_id, "value": "a new secret value"}]
    _, response = await sanic_client.patch(
        f"/api/data/projects/{project_id}/session_secrets", headers=user_headers, json=patch
    )
    assert response.status_code == 200, response.json
    session_secrets = response.json
    _, response = await sanic_client.get("/api/data/user/secrets", headers=user_headers)
    assert response.status_code == 200, response.text
    user_secrets = response.json
    existing_user_secret = user_secrets[0]

    patch = [{"secret_slot_id": secret_slot_id, "value": "an updated secret value"}]
    _, response = await sanic_client.patch(
        f"/api/data/projects/{project_id}/session_secrets", headers=user_headers, json=patch
    )

    assert response.status_code == 200, response.text
    assert response.json is not None
    session_secrets = response.json
    assert len(session_secrets) == 1
    assert session_secrets[0].get("secret_slot") is not None
    assert session_secrets[0]["secret_slot"].get("id") == secret_slot_id
    assert session_secrets[0]["secret_slot"].get("name") == secret_slot["name"]
    assert session_secrets[0]["secret_slot"].get("filename") == secret_slot["filename"]
    assert session_secrets[0].get("secret_id") == existing_user_secret["id"]

    # Check that the secrets are returned from a GET request
    _, response = await sanic_client.get(f"/api/data/projects/{project_id}/session_secrets", headers=user_headers)
    assert response.status_code == 200, response.json
    assert response.json is not None
    session_secrets = response.json
    assert len(session_secrets) == 1
    assert session_secrets[0].get("secret_slot") is not None
    assert session_secrets[0]["secret_slot"].get("id") == secret_slot_id
    assert session_secrets[0].get("secret_id") == existing_user_secret["id"]


@pytest.mark.asyncio
async def test_patch_session_secrets_unlink_secret_with_null(
    sanic_client: SanicASGITestClient, create_project, create_session_secret_slot, user_headers
) -> None:
    project = await create_project(sanic_client, "My project")
    project_id = project["id"]
    secret_slot = await create_session_secret_slot(project_id, "test_secret")
    secret_slot_id = secret_slot["id"]
    patch = [{"secret_slot_id": secret_slot_id, "value": "a new secret value"}]
    _, response = await sanic_client.patch(
        f"/api/data/projects/{project_id}/session_secrets", headers=user_headers, json=patch
    )
    assert response.status_code == 200, response.json
    session_secrets = response.json
    _, response = await sanic_client.get("/api/data/user/secrets", headers=user_headers)
    assert response.status_code == 200, response.text
    user_secrets = response.json
    existing_user_secret = user_secrets[0]

    patch = [{"secret_slot_id": secret_slot_id, "value": None}]
    _, response = await sanic_client.patch(
        f"/api/data/projects/{project_id}/session_secrets", headers=user_headers, json=patch
    )

    assert response.status_code == 200, response.text
    assert response.json is not None
    session_secrets = response.json
    assert len(session_secrets) == 0

    # Check that the secrets are returned from a GET request
    _, response = await sanic_client.get(f"/api/data/projects/{project_id}/session_secrets", headers=user_headers)
    assert response.status_code == 200, response.json
    assert response.json is not None
    session_secrets = response.json
    assert len(session_secrets) == 0
    # Check that the user secret has been preserved
    _, response = await sanic_client.get("/api/data/user/secrets", headers=user_headers)
    assert response.status_code == 200, response.text
    user_secrets = response.json
    assert len(user_secrets) == 1
    assert {s["id"] for s in user_secrets} == {existing_user_secret["id"]}


@pytest.mark.asyncio
async def test_delete_session_secrets(
    sanic_client: SanicASGITestClient, create_project, create_session_secret_slot, user_headers
) -> None:
    project = await create_project(sanic_client, "My project")
    project_id = project["id"]
    secret_slot = await create_session_secret_slot(project_id, "test_secret")
    secret_slot_id = secret_slot["id"]
    patch = [{"secret_slot_id": secret_slot_id, "value": "a new secret value"}]
    _, response = await sanic_client.patch(
        f"/api/data/projects/{project_id}/session_secrets", headers=user_headers, json=patch
    )
    assert response.status_code == 200, response.json

    _, response = await sanic_client.delete(f"/api/data/projects/{project_id}/session_secrets", headers=user_headers)

    assert response.status_code == 204, response.text

    # Check that the secrets are returned from a GET request
    _, response = await sanic_client.get(f"/api/data/projects/{project_id}/session_secrets", headers=user_headers)
    assert response.status_code == 200, response.json
    assert response.json is not None
    session_secrets = response.json
    assert len(session_secrets) == 0
