"""Tests for sessions blueprint."""

import json
from test.bases.renku_data_services.keycloak_sync.test_sync import get_kc_users
from typing import Any, Dict, List

import pytest
import pytest_asyncio
from sanic import Sanic
from sanic_testing.testing import SanicASGITestClient

from renku_data_services.app_config import Config
from renku_data_services.data_api.app import register_all_handlers
from renku_data_services.users.dummy_kc_api import DummyKeycloakAPI
from renku_data_services.users.models import UserInfo


@pytest.fixture
def users() -> List[UserInfo]:
    return [
        UserInfo("admin", "Admin", "Doe", "admin.doe@gmail.com"),
        UserInfo("user", "User", "Doe", "user.doe@gmail.com"),
        UserInfo("member-1", "Member-1", "Doe", "member-1.doe@gmail.com"),
        UserInfo("member-2", "Member-2", "Doe", "member-2.doe@gmail.com"),
    ]


@pytest_asyncio.fixture
async def sanic_client(app_config: Config, users: List[UserInfo]) -> SanicASGITestClient:
    app_config.kc_api = DummyKeycloakAPI(users=get_kc_users(users))
    app = Sanic(app_config.app_name)
    app = register_all_handlers(app, app_config)
    await app_config.kc_user_repo.initialize(app_config.kc_api)
    return SanicASGITestClient(app)


@pytest.fixture
def admin_headers() -> Dict[str, str]:
    """Authentication headers for an admin user."""
    access_token = json.dumps({"is_admin": True, "id": "admin", "name": "Admin User"})
    return {"Authorization": f"Bearer {access_token}"}


@pytest.fixture
def user_headers() -> Dict[str, str]:
    """Authentication headers for a normal user."""
    access_token = json.dumps({"is_admin": False, "id": "user", "name": "Normal User"})
    return {"Authorization": f"Bearer {access_token}"}


@pytest.fixture
def unauthorized_headers() -> Dict[str, str]:
    """Authentication headers for an anonymous user (did not log in)."""
    return {"Authorization": "Bearer {}"}


@pytest.fixture
def create_project(sanic_client, user_headers, admin_headers):
    async def create_project_helper(name: str, admin: bool = False, **payload) -> Dict[str, Any]:
        headers = admin_headers if admin else user_headers
        payload = payload.copy()
        payload.update({"name": name})

        _, response = await sanic_client.post("/api/data/projects", headers=headers, json=payload)

        assert response.status_code == 201, response.text
        return response.json

    return create_project_helper


@pytest.fixture
def create_session(sanic_client, user_headers, admin_headers):
    async def create_session_helper(name: str, project_id: str, admin: bool = False, **payload) -> Dict[str, Any]:
        headers = admin_headers if admin else user_headers
        payload = payload.copy()
        payload.update({"name": name, "project_id": project_id})
        payload["environment_id"] = payload.get("environment_id") or "http://renkulab.io/repository-1/Dockerfile:0.0.1"

        _, response = await sanic_client.post("/api/data/sessions", headers=headers, json=payload)

        assert response.status_code == 201, response.text
        return response.json

    return create_session_helper


@pytest.mark.asyncio
async def test_session_creation(sanic_client, user_headers, admin_headers, create_project):
    await create_project("Project 1")
    project = await create_project("Project 2")
    await create_project("Project 3")

    payload = {
        "name": "Compute Session",
        "description": "First Renku 1.0 compute session",
        "environment_id": "http://renkulab.io/repository-1/Dockerfile:0.0.1",
        "project_id": project["id"],
    }

    _, response = await sanic_client.post("/api/data/sessions", headers=admin_headers, json=payload)

    assert response.status_code == 201, response.text
    session = response.json
    assert session["name"] == "Compute Session"
    assert session["description"] == "First Renku 1.0 compute session"

    session_id = session["id"]
    _, response = await sanic_client.get(f"/api/data/sessions/{session_id}", headers=user_headers)

    assert response.status_code == 200, response.text
    session = response.json
    assert session["name"] == "Compute Session"
    assert session["description"] == "First Renku 1.0 compute session"


@pytest.mark.asyncio
async def test_get_all_sessions(create_project, create_session, sanic_client, user_headers):
    # Create some projects
    await create_project("Project 1")
    project = await create_project("Project 2")
    await create_project("Project 3")

    await create_session(name="Session 1", project_id=project["id"])
    await create_session(name="Session 2", project_id=project["id"])
    await create_session(name="Session 3", project_id=project["id"])

    _, response = await sanic_client.get("/api/data/sessions", headers=user_headers)

    assert response.status_code == 200, response.text
    sessions = response.json

    assert {p["name"] for p in sessions} == {"Session 1", "Session 2", "Session 3"}


@pytest.mark.asyncio
async def test_delete_project(create_project, create_session, sanic_client, user_headers):
    # Create some projects
    await create_project("Project 1")
    project = await create_project("Project 2")
    await create_project("Project 3")

    await create_session(name="Session 1", project_id=project["id"])
    await create_session(name="Session 2", project_id=project["id"])
    session = await create_session(name="Session 3", project_id=project["id"])
    await create_session(name="Session 4", project_id=project["id"])
    await create_session(name="Session 5", project_id=project["id"])

    # Delete a session
    session_id = session["id"]
    _, response = await sanic_client.delete(f"/api/data/sessions/{session_id}", headers=user_headers)

    assert response.status_code == 204, response.text

    # Get all sessions
    _, response = await sanic_client.get("/api/data/sessions", headers=user_headers)

    assert response.status_code == 200, response.text
    assert {p["name"] for p in response.json} == {"Session 1", "Session 2", "Session 4", "Session 5"}


@pytest.mark.asyncio
async def test_patch_session(create_project, create_session, sanic_client, user_headers):
    # Create some projects
    await create_project("Project 1")
    project = await create_project("Project 2")
    await create_project("Project 3")

    session = await create_session(name="Session 1", project_id=project["id"], description="Old description")

    # Patch a session
    patch = {
        "name": "New Name",
        "description": "A patched session",
        "environment_id": "http://renkulab.io/repository-2/Dockerfile:2.0.0",
    }
    session_id = session["id"]
    _, response = await sanic_client.patch(f"/api/data/sessions/{session_id}", headers=user_headers, json=patch)

    assert response.status_code == 200, response.text

    # Get the session
    session_id = session["id"]
    _, response = await sanic_client.get(f"/api/data/sessions/{session_id}", headers=user_headers)

    assert response.status_code == 200, response.text
    session = response.json
    assert session["name"] == "New Name"
    assert session["description"] == "A patched session"
    assert session["environment_id"] == "http://renkulab.io/repository-2/Dockerfile:2.0.0"
