"""Tests for projects blueprint."""

import time
import uuid
from typing import Any, Dict

import pytest
from sanic import Sanic
from sanic_testing.testing import SanicASGITestClient

from renku_data_services.config import Config
from renku_data_services.data_api.app import register_all_handlers


@pytest.fixture
def sanic_client(app_config: Config) -> SanicASGITestClient:
    app = Sanic(app_config.app_name)
    app = register_all_handlers(app, app_config)
    return SanicASGITestClient(app)


@pytest.fixture
def admin_headers() -> Dict[str, str]:
    """Authentication headers for an admin user."""
    return {"Authorization": 'Bearer {"is_admin": true, "id": "admin", "name": "Admin User"}'}


@pytest.fixture
def user_headers() -> Dict[str, str]:
    """Authentication headers for a normal user."""
    return {"Authorization": 'Bearer {"is_admin": false, "id": "user", "name": "Normal User"}'}


@pytest.fixture
def create_project(sanic_client, user_headers, admin_headers):
    async def create_project_helper(name: str, admin: bool = False, **kwargs) -> Dict[str, Any]:
        headers = admin_headers if admin else user_headers
        payload = kwargs.copy()
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
    assert set(project["repositories"]) == {"http://renkulab.io/repository-1", "http://renkulab.io/repository-2"}

    project_id = project["id"]
    _, response = await sanic_client.get(f"/api/data/projects/{project_id}", headers=user_headers)

    assert response.status_code == 200, response.text
    project = response.json
    assert project["name"] == "Renku Native Project"
    assert project["slug"] == "project-slug"
    assert project["description"] == "First Renku native project"
    assert project["visibility"] == "public"
    assert project["created_by"] == {"id": "user"}
    assert set(project["repositories"]) == {"http://renkulab.io/repository-1", "http://renkulab.io/repository-2"}


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
    assert "repositories" not in project or project["repositories"] is None


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
@pytest.mark.xfail(reason="Authorization isn't implemented yet")
async def test_get_all_projects(create_project, sanic_client, user_headers):
    payload = {
        "slug": f"slug-{uuid.uuid4()}",
        "description": "Renku native project",
        "visibility": "private",
        "repositories": ["http://renkulab.io/repository-1", "http://renkulab.io/repository-2"],
    }
    # Create some projects
    await create_project("Project 1", admin=True, **payload)
    await create_project("Project 2", **payload)
    await create_project("Project 3", admin=True, **payload)
    await create_project("Project 4", **payload)
    await create_project("Project 5", **payload)

    # Get all non-admin projects
    _, response = await sanic_client.get(f"/api/data/projects", headers=user_headers)

    assert response.status_code == 200, response.text
    projects = response.json

    assert [p["name"] for p in projects] == ["Project 2", "Project 4", "Project 5"]


@pytest.mark.asyncio
async def test_get_all_projects_with_pagination(create_project, sanic_client, user_headers):
    # Create some projects
    for i in range(1, 10):
        await create_project(f"Project {i}")
        # NOTE: This delay is required for projects to be created in order
        time.sleep(0.5)

    parameters = {"page": 2, "per_page": 3}
    _, response = await sanic_client.get(f"/api/data/projects", headers=user_headers, params=parameters)

    assert response.status_code == 200, response.text
    projects = response.json

    assert {p["name"] for p in projects} == {"Project 4", "Project 5", "Project 6"}
    assert response.headers["page"] == "2"
    assert response.headers["per-page"] == "3"
    assert response.headers["total"] == "9"
    assert response.headers["total-pages"] == "3"

    parameters = {"page": 3, "per_page": 4}
    _, response = await sanic_client.get(f"/api/data/projects", headers=user_headers, params=parameters)

    assert response.status_code == 200, response.text
    projects = response.json

    assert {p["name"] for p in projects} == {"Project 9"}
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

    _, response = await sanic_client.get(f"/api/data/projects", headers=user_headers)

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
    _, response = await sanic_client.get(f"/api/data/projects", headers=user_headers, params=parameters)

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
    _, response = await sanic_client.get(f"/api/data/projects", headers=user_headers, params=parameters)

    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_pagination_with_invalid_per_page(create_project, sanic_client, user_headers):
    parameters = {"per_page": 0}
    _, response = await sanic_client.get(f"/api/data/projects", headers=user_headers, params=parameters)

    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_result_is_sorted_by_creation_date(create_project, sanic_client, user_headers):
    # Create some projects
    for i in range(1, 5):
        await create_project(f"Project {i}")
        # NOTE: This delay is required for projects to be created in order
        time.sleep(1.5)

    _, response = await sanic_client.get(f"/api/data/projects", headers=user_headers)

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
    _, response = await sanic_client.get(f"/api/data/projects", headers=user_headers)

    assert response.status_code == 200, response.text
    assert [p["name"] for p in response.json] == ["Project 1", "Project 2", "Project 4", "Project 5"]


@pytest.mark.asyncio
async def test_patch_project(create_project, get_project, sanic_client, user_headers):
    # Create some projects
    await create_project("Project 1")
    project = await create_project("Project 2")
    await create_project("Project 3")

    # Patch a project
    patch = {
        "name": "New Name",
        "slug": "new-slug",
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
    assert project["slug"] == "new-slug"
    assert project["description"] == "A patched Renku native project"
    assert project["visibility"] == "public"
    assert set(project["repositories"]) == {"http://renkulab.io/repository-1", "http://renkulab.io/repository-2"}
