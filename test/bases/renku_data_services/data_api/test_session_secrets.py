"""Tests for session secrets blueprint."""

import pytest
from sanic_testing.testing import SanicASGITestClient


@pytest.mark.asyncio
async def test_patch_session_secrets(sanic_client: SanicASGITestClient, create_project, user_headers) -> None:
    project = await create_project("My project")
    project_id = project["id"]
    payload = {
        "project_id": project_id,
        "filename": "test_secret",
    }
    _, response = await sanic_client.post("/api/data/session_secret_slots", headers=user_headers, json=payload)
    assert response.status_code == 201, response.text
    session_secret_slot = response.json
    payload = {"name": "my-user-secret", "value": "a secret value", "kind": "general"}
    _, response = await sanic_client.post("/api/data/user/secrets", headers=user_headers, json=payload)
    assert response.status_code == 201, response.text
    user_secret = response.json

    patch = [{"secret_slot_id": session_secret_slot["id"], "secret_id": user_secret["id"]}]

    _, response = await sanic_client.patch(f"/api/data/projects/{project_id}/secrets", headers=user_headers, json=patch)
    assert response.status_code == 200, response.text
    assert response.json is not None
    session_secrets = response.json
    assert len(session_secrets) == 1
    assert session_secrets[0].get("secret_slot") is not None
    assert session_secrets[0]["secret_slot"].get("id") == session_secret_slot["id"]
    assert session_secrets[0]["secret_slot"].get("name") == session_secret_slot["name"]
    assert session_secrets[0]["secret_slot"].get("filename") == session_secret_slot["filename"]
    assert session_secrets[0].get("secret_id") == user_secret["id"]
