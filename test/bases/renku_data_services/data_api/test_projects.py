"""Tests for projects blueprint."""

import json
import time
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
def get_project(sanic_client, user_headers, admin_headers):
    async def get_project_helper(project_id: str, admin: bool = False) -> Dict[str, Any]:
        headers = admin_headers if admin else user_headers
        _, response = await sanic_client.get(f"/api/data/projects/{project_id}", headers=headers)

        assert response.status_code == 200, response.text
        return response.json

    return get_project_helper


@pytest.mark.asyncio
async def test_project_creation(sanic_client, user_headers):
    payload = {
        "name": "Renku Native Project",
        "slug": "project-slug",
        "description": "First Renku native project",
        "visibility": "public",
        "repositories": ["http://renkulab.io/repository-1", "http://renkulab.io/repository-2"],
    }

    _, response = await sanic_client.post("/api/data/projects", headers=user_headers, json=payload)

    assert response.status_code == 201, response.text
    project = response.json
    assert project["name"] == "Renku Native Project"
    assert project["slug"] == "project-slug"
    assert project["description"] == "First Renku native project"
    assert project["visibility"] == "public"
    assert project["created_by"] == {"id": "user"}
    assert {r for r in project["repositories"]} == {
        "http://renkulab.io/repository-1",
        "http://renkulab.io/repository-2",
    }

    project_id = project["id"]
    _, response = await sanic_client.get(f"/api/data/projects/{project_id}", headers=user_headers)

    assert response.status_code == 200, response.text
    project = response.json
    assert project["name"] == "Renku Native Project"
    assert project["slug"] == "project-slug"
    assert project["description"] == "First Renku native project"
    assert project["visibility"] == "public"
    assert project["created_by"] == {"id": "user"}
    assert {r for r in project["repositories"]} == {
        "http://renkulab.io/repository-1",
        "http://renkulab.io/repository-2",
    }


@pytest.mark.asyncio
async def test_project_creation_with_default_values(sanic_client, user_headers, get_project):
    payload = {
        "name": "Project with Default Values",
    }

    _, response = await sanic_client.post("/api/data/projects", headers=user_headers, json=payload)

    assert response.status_code == 201, response.text

    project = await get_project(project_id=response.json["id"])

    assert project["name"] == "Project with Default Values"
    assert project["slug"] == "project-with-default-values"
    assert "description" not in project or project["description"] is None
    assert project["visibility"] == "private"
    assert project["created_by"] == {"id": "user"}
    assert len(project["repositories"]) == 0


@pytest.mark.asyncio
async def test_create_project_with_invalid_visibility(sanic_client, user_headers):
    _, response = await sanic_client.post("/api/data/projects", headers=user_headers, json={"visibility": "random"})

    assert response.status_code == 422, response.text
    assert "visibility: Input should be 'private' or 'public'" in response.json["error"]["message"]


@pytest.mark.asyncio
async def test_get_a_project(create_project, get_project):
    # Create some projects
    await create_project("Project 1")
    project = await create_project("Project 2")
    await create_project("Project 3")

    # Get a single project
    project = await get_project(project_id=project["id"])

    assert project["name"] == "Project 2"


@pytest.mark.asyncio
async def test_get_all_projects_with_pagination(create_project, sanic_client, user_headers):
    # Create some projects
    for i in range(1, 10):
        await create_project(f"Project {i}")
        # NOTE: This delay is required for projects to be created in order
        time.sleep(1.5)

    parameters = {"page": 2, "per_page": 3}
    _, response = await sanic_client.get("/api/data/projects", headers=user_headers, params=parameters)

    assert response.status_code == 200, response.text
    projects = response.json

    assert {p["name"] for p in projects} == {"Project 4", "Project 5", "Project 6"}
    assert response.headers["page"] == "2"
    assert response.headers["per-page"] == "3"
    assert response.headers["total"] == "9"
    assert response.headers["total-pages"] == "3"

    parameters = {"page": 3, "per_page": 4}
    _, response = await sanic_client.get("/api/data/projects", headers=user_headers, params=parameters)

    assert response.status_code == 200, response.text
    projects = response.json

    assert {p["name"] for p in projects} == {"Project 1"}
    assert response.headers["page"] == "3"
    assert response.headers["per-page"] == "4"
    assert response.headers["total"] == "9"
    assert response.headers["total-pages"] == "3"


@pytest.mark.asyncio
async def test_default_pagination(create_project, sanic_client, user_headers):
    # Create some projects
    await create_project("Project 1")
    await create_project("Project 2")
    await create_project("Project 3")

    _, response = await sanic_client.get("/api/data/projects", headers=user_headers)

    assert response.status_code == 200, response.text

    assert response.headers["page"] == "1"
    assert response.headers["per-page"] == "20"
    assert response.headers["total"] == "3"
    assert response.headers["total-pages"] == "1"


@pytest.mark.asyncio
async def test_pagination_with_non_existing_page(create_project, sanic_client, user_headers):
    # Create some projects
    await create_project("Project 1")
    await create_project("Project 2")
    await create_project("Project 3")

    parameters = {"page": 42, "per_page": 3}
    _, response = await sanic_client.get("/api/data/projects", headers=user_headers, params=parameters)

    assert response.status_code == 200, response.text
    projects = response.json

    assert len(projects) == 0
    assert response.headers["page"] == "42"
    assert response.headers["per-page"] == "3"
    assert response.headers["total"] == "3"
    assert response.headers["total-pages"] == "1"


@pytest.mark.asyncio
async def test_pagination_with_invalid_page(create_project, sanic_client, user_headers):
    parameters = {"page": 0}
    _, response = await sanic_client.get("/api/data/projects", headers=user_headers, params=parameters)

    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_pagination_with_invalid_per_page(create_project, sanic_client, user_headers):
    parameters = {"per_page": 0}
    _, response = await sanic_client.get("/api/data/projects", headers=user_headers, params=parameters)

    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_result_is_sorted_by_creation_date(create_project, sanic_client, user_headers):
    # Create some projects
    for i in range(1, 5):
        await create_project(f"Project {i}")
        # NOTE: This delay is required for projects to be created in order
        time.sleep(1.5)

    _, response = await sanic_client.get("/api/data/projects", headers=user_headers)

    assert response.status_code == 200, response.text
    projects = response.json

    assert [p["name"] for p in projects] == ["Project 4", "Project 3", "Project 2", "Project 1"]


@pytest.mark.asyncio
async def test_delete_project(create_project, sanic_client, user_headers):
    # Create some projects
    await create_project("Project 1")
    await create_project("Project 2")
    project = await create_project("Project 3")
    await create_project("Project 4")
    await create_project("Project 5")

    # Delete a project
    project_id = project["id"]
    _, response = await sanic_client.delete(f"/api/data/projects/{project_id}", headers=user_headers)

    assert response.status_code == 204, response.text

    # Get all projects
    _, response = await sanic_client.get("/api/data/projects", headers=user_headers)

    assert response.status_code == 200, response.text
    assert {p["name"] for p in response.json} == {"Project 1", "Project 2", "Project 4", "Project 5"}


@pytest.mark.asyncio
async def test_patch_project(create_project, get_project, sanic_client, user_headers):
    # Create some projects
    await create_project("Project 1")
    project = await create_project("Project 2", repositories=["http://renkulab.io/repository-0"])
    await create_project("Project 3")

    # Patch a project
    patch = {
        "name": "New Name",
        "description": "A patched Renku native project",
        "visibility": "public",
        "repositories": ["http://renkulab.io/repository-1", "http://renkulab.io/repository-2"],
    }
    project_id = project["id"]
    _, response = await sanic_client.patch(f"/api/data/projects/{project_id}", headers=user_headers, json=patch)

    assert response.status_code == 200, response.text

    # Get the project
    project = await get_project(project_id=project_id)

    assert project["name"] == "New Name"
    assert project["slug"] == project["slug"]
    assert project["description"] == "A patched Renku native project"
    assert project["visibility"] == "public"
    assert {r for r in project["repositories"]} == {
        "http://renkulab.io/repository-1",
        "http://renkulab.io/repository-2",
    }


@pytest.mark.asyncio
async def test_patch_visibility_to_private_hides_project(create_project, admin_headers, sanic_client, user_headers):
    project = await create_project("Project 1", admin=True, visibility="public")

    _, response = await sanic_client.get("/api/data/projects", headers=user_headers)
    assert response.json[0]["name"] == "Project 1"

    patch = {
        "visibility": "private",
    }
    project_id = project["id"]
    _, response = await sanic_client.patch(f"/api/data/projects/{project_id}", headers=admin_headers, json=patch)
    assert response.status_code == 200, response.text

    _, response = await sanic_client.get("/api/data/projects", headers=user_headers)

    assert len(response.json) == 0


@pytest.mark.asyncio
async def test_patch_visibility_to_public_shows_project(create_project, admin_headers, sanic_client, user_headers):
    project = await create_project("Project 1", admin=True, visibility="private")

    _, response = await sanic_client.get("/api/data/projects", headers=user_headers)
    assert len(response.json) == 0

    patch = {
        "visibility": "public",
    }
    project_id = project["id"]
    _, response = await sanic_client.patch(f"/api/data/projects/{project_id}", headers=admin_headers, json=patch)
    assert response.status_code == 200, response.text

    _, response = await sanic_client.get("/api/data/projects", headers=user_headers)

    assert response.json[0]["name"] == "Project 1"


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["id", "slug", "created_by", "creation_date"])
async def test_cannot_patch_reserved_fields(create_project, get_project, sanic_client, user_headers, field):
    project = await create_project("Project 1")
    original_value = project[field]

    # Try to patch the project
    patch = {
        field: "new-value",
    }
    project_id = project["id"]
    _, response = await sanic_client.patch(f"/api/data/projects/{project_id}", headers=user_headers, json=patch)

    assert response.status_code == 422
    assert f"{field}: Extra inputs are not permitted" in response.text

    # Check that the field's value didn't change
    project = await get_project(project_id=project_id)

    assert project[field] == original_value


@pytest.mark.asyncio
async def test_get_all_projects_for_specific_user(
    create_project, sanic_client, user_headers, admin_headers, unauthorized_headers
):
    await create_project("Project 1", visibility="private")
    await create_project("Project 2", visibility="public")
    await create_project("Project 3", admin=True)
    await create_project("Project 4", admin=True, visibility="public")

    _, response = await sanic_client.get("/api/data/projects", headers=user_headers)

    assert response.status_code == 200, response.text
    projects = response.json

    # A non-admin can only see her projects and public projects
    assert {p["name"] for p in projects} == {"Project 1", "Project 2", "Project 4"}

    _, response = await sanic_client.get("/api/data/projects", headers=admin_headers)

    assert response.status_code == 200, response.text
    projects = response.json

    # An admin can see all projects
    assert {p["name"] for p in projects} == {"Project 1", "Project 2", "Project 3", "Project 4"}

    _, response = await sanic_client.get("/api/data/projects", headers=unauthorized_headers)

    assert response.status_code == 200, response.text
    projects = response.json

    # An anonymous user can only see public projects
    assert {p["name"] for p in projects} == {"Project 2", "Project 4"}


@pytest.mark.asyncio
async def test_unauthorized_user_cannot_create_delete_or_modify_projects(
    create_project, sanic_client, unauthorized_headers
):
    payload = {
        "name": "Renku Native Project",
        "slug": "project-slug",
    }

    _, response = await sanic_client.post("/api/data/projects", headers=unauthorized_headers, json=payload)

    assert response.status_code == 401, response.text

    project = await create_project("Project 1")
    project_id = project["id"]

    _, response = await sanic_client.patch(f"/api/data/projects/{project_id}", headers=unauthorized_headers, json={})

    assert response.status_code == 401, response.text

    _, response = await sanic_client.delete(f"/api/data/projects/{project_id}", headers=unauthorized_headers)

    assert response.status_code == 401, response.text


@pytest.mark.asyncio
async def test_creator_is_added_as_owner_members(sanic_client, user_headers):
    payload = {
        "name": "Project with Default Values",
    }

    _, response = await sanic_client.post("/api/data/projects", headers=user_headers, json=payload)

    project_id = response.json["id"]

    _, response = await sanic_client.get(f"/api/data/projects/{project_id}/members", headers=user_headers)

    assert response.status_code == 200, response.text

    assert len(response.json) == 1
    member = response.json[0]
    assert member["member"] == {"id": "user", "email": "user.doe@gmail.com", "first_name": "User", "last_name": "Doe"}
    assert member["role"] == "owner"


@pytest.mark.asyncio
async def test_add_project_members(create_project, sanic_client, user_headers, admin_headers):
    project = await create_project("Project 1")
    project_id = project["id"]

    members = [{"member": {"id": "member-1"}, "role": "member"}, {"member": {"id": "member-2"}, "role": "owner"}]

    _, response = await sanic_client.patch(
        f"/api/data/projects/{project_id}/members", headers=user_headers, json=members
    )

    assert response.status_code == 200, response.text

    # TODO: Should project owner be able to see the project members -> Replace the header with ``user_headers``
    _, response = await sanic_client.get(f"/api/data/projects/{project_id}/members", headers=admin_headers)

    assert response.status_code == 200, response.text

    assert len(response.json) == 3
    member = next(m for m in response.json if m["member"]["id"] == "user")
    assert member["role"] == "owner"
    member = next(m for m in response.json if m["member"]["id"] == "member-1")
    assert member["role"] == "member"
    member = next(m for m in response.json if m["member"]["id"] == "member-2")
    assert member["role"] == "owner"


@pytest.mark.asyncio
@pytest.mark.xfail(reason="Project owner cannot query project members.")
async def test_delete_project_members(create_project, sanic_client, user_headers):
    project = await create_project("Project 1")
    project_id = project["id"]

    members = [{"member": {"id": "member-1"}, "role": "member"}, {"member": {"id": "member-2"}, "role": "owner"}]
    await sanic_client.patch(f"/api/data/projects/{project_id}/members", headers=user_headers, json=members)

    _, response = await sanic_client.delete(f"/api/data/projects/{project_id}/members/member-1", headers=user_headers)

    assert response.status_code == 204, response.text

    _, response = await sanic_client.get(f"/api/data/projects/{project_id}/members", headers=user_headers)

    assert response.status_code == 200, response.text

    assert len(response.json) == 1
    member = response.json[0]
    assert member["member"] == {"id": "user", "email": "user.doe@gmail.com", "first_name": "User", "last_name": "Doe"}
    assert member["role"] == "owner"