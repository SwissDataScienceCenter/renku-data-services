"""Tests for session secrets blueprint."""

from typing import Any

import pytest
from sanic_testing.testing import SanicASGITestClient
from ulid import ULID

from renku_data_services.users.models import UserInfo


@pytest.fixture
def create_session_secret_slot(sanic_client: SanicASGITestClient, regular_user: UserInfo, user_headers):
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
    project = await create_project("My project")
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
    project = await create_project("My project")
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
    project = await create_project("My project", admin=True)
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
    project = await create_project("My project")
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
    project = await create_project("My project")
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
    project = await create_project("My project")
    project_id = project["id"]

    for i in range(1, 10):
        await create_session_secret_slot(project_id, f"secret_slot_{i}")

    _, response = await sanic_client.get(f"/api/data/projects/{project_id}/secret_slots", headers=user_headers)

    assert response.status_code == 200, response.text
    assert response.json is not None
    secret_slots = response.json
    assert {secret_slot["filename"] for secret_slot in secret_slots} == {f"secret_slot_{i}" for i in range(1, 10)}
