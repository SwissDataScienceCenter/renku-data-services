"""Tests for projects blueprint."""

import time
from base64 import b64decode
from typing import Any

import pytest
from sqlalchemy import select
from ulid import ULID

from components.renku_data_services.message_queue.avro_models.io.renku.events import v2 as avro_schema_v2
from renku_data_services.app_config.config import Config
from renku_data_services.message_queue.avro_models.io.renku.events.v2.member_role import MemberRole
from renku_data_services.message_queue.models import deserialize_binary
from renku_data_services.users.models import UserInfo
from test.bases.renku_data_services.data_api.utils import deserialize_event, merge_headers


@pytest.fixture
def get_project(sanic_client, user_headers, admin_headers):
    async def get_project_helper(project_id: str, admin: bool = False) -> dict[str, Any]:
        headers = admin_headers if admin else user_headers
        _, response = await sanic_client.get(f"/api/data/projects/{project_id}", headers=headers)

        assert response.status_code == 200, response.text
        return response.json

    return get_project_helper


@pytest.mark.asyncio
async def test_project_creation(sanic_client, user_headers, regular_user: UserInfo, app_config) -> None:
    payload = {
        "name": "Renku Native Project",
        "slug": "project-slug",
        "description": "First Renku native project",
        "visibility": "public",
        "repositories": ["http://renkulab.io/repository-1", "http://renkulab.io/repository-2"],
        "namespace": regular_user.namespace.slug,
        "keywords": ["keyword 1", "keyword.2", "keyword-3", "KEYWORD_4"],
        "documentation": "$\\sqrt(2)$",
    }

    await app_config.event_repo.delete_all_events()

    _, response = await sanic_client.post("/api/data/projects", headers=user_headers, json=payload)

    assert response.status_code == 201, response.text
    project = response.json
    assert project["name"] == "Renku Native Project"
    assert project["slug"] == "project-slug"
    assert project["description"] == "First Renku native project"
    assert project["visibility"] == "public"
    assert {r for r in project["repositories"]} == {
        "http://renkulab.io/repository-1",
        "http://renkulab.io/repository-2",
    }
    assert set(project["keywords"]) == {"keyword 1", "keyword.2", "keyword-3", "KEYWORD_4"}
    assert "documentation" not in project
    assert project["created_by"] == "user"
    assert "template_id" not in project or project["template_id"] is None
    project_id = project["id"]

    events = await app_config.event_repo.get_pending_events()
    assert len(events) == 2
    project_created_event = next((e for e in events if e.get_message_type() == "project.created"), None)
    assert project_created_event
    created_event = deserialize_binary(
        b64decode(project_created_event.payload["payload"]), avro_schema_v2.ProjectCreated
    )
    assert created_event.name == payload["name"]
    assert created_event.slug == payload["slug"]
    assert created_event.repositories == payload["repositories"]
    project_auth_added = next((e for e in events if e.get_message_type() == "projectAuth.added"), None)
    assert project_auth_added
    auth_event = deserialize_binary(b64decode(project_auth_added.payload["payload"]), avro_schema_v2.ProjectMemberAdded)
    assert auth_event.userId == "user"
    assert auth_event.role == MemberRole.OWNER

    _, response = await sanic_client.get(f"/api/data/projects/{project_id}", headers=user_headers)

    assert response.status_code == 200, response.text
    project = response.json
    assert project["name"] == "Renku Native Project"
    assert project["slug"] == "project-slug"
    assert project["description"] == "First Renku native project"
    assert project["visibility"] == "public"
    assert {r for r in project["repositories"]} == {
        "http://renkulab.io/repository-1",
        "http://renkulab.io/repository-2",
    }
    assert set(project["keywords"]) == {"keyword 1", "keyword.2", "keyword-3", "KEYWORD_4"}
    assert "documentation" not in project
    assert project["created_by"] == "user"

    _, response = await sanic_client.get(
        f"/api/data/projects/{project_id}", params={"with_documentation": True}, headers=user_headers
    )

    assert response.status_code == 200, response.text
    project = response.json
    assert project["documentation"] == "$\\sqrt(2)$"
    assert "template_id" not in project or project["template_id"] is None

    # same as above, but using namespace/slug to retrieve the pr
    _, response = await sanic_client.get(
        f"/api/data/namespaces/{payload['namespace']}/projects/{payload['slug']}",
        params={"with_documentation": True},
        headers=user_headers,
    )

    assert response.status_code == 200, response.text
    project = response.json
    assert project["name"] == "Renku Native Project"
    assert project["slug"] == "project-slug"
    assert project["namespace"] == regular_user.namespace.slug
    assert project["documentation"] == "$\\sqrt(2)$"


@pytest.mark.asyncio
async def test_project_creation_with_default_values(
    sanic_client, user_headers, regular_user: UserInfo, get_project
) -> None:
    payload = {
        "name": "Project with Default Values",
        "namespace": regular_user.namespace.slug,
    }

    _, response = await sanic_client.post("/api/data/projects", headers=user_headers, json=payload)

    assert response.status_code == 201, response.text

    project = await get_project(project_id=response.json["id"])

    assert project["name"] == "Project with Default Values"
    assert project["slug"] == "project-with-default-values"
    assert "description" not in project or project["description"] is None
    assert project["visibility"] == "private"
    assert project["created_by"] == "user"
    assert len(project["keywords"]) == 0
    assert len(project["repositories"]) == 0


@pytest.mark.asyncio
async def test_create_project_with_invalid_visibility(sanic_client, user_headers) -> None:
    _, response = await sanic_client.post("/api/data/projects", headers=user_headers, json={"visibility": "random"})

    assert response.status_code == 422, response.text
    assert "visibility: Input should be 'private' or 'public'" in response.json["error"]["message"]


@pytest.mark.asyncio
@pytest.mark.parametrize("keyword", ["invalid chars '", "Nön English"])
async def test_create_project_with_invalid_keywords(sanic_client, user_headers, keyword) -> None:
    _, response = await sanic_client.post("/api/data/projects", headers=user_headers, json={"keywords": [keyword]})

    assert response.status_code == 422, response.text
    assert "String should match pattern '^[A-Za-z0-9\\s\\-_.]*$'" in response.json["error"]["message"]


@pytest.mark.asyncio
async def test_project_creation_with_invalid_namespace(sanic_client, user_headers, member_1_user: UserInfo) -> None:
    namespace = member_1_user.namespace.slug
    _, response = await sanic_client.get(f"/api/data/namespaces/{namespace}", headers=user_headers)
    assert response.status_code == 200, response.text
    payload = {
        "name": "Project with Default Values",
        "namespace": namespace,
    }

    _, response = await sanic_client.post("/api/data/projects", headers=user_headers, json=payload)

    assert response.status_code == 403, response.text
    assert "you do not have sufficient permissions" in response.json["error"]["message"]


@pytest.mark.asyncio
async def test_project_creation_with_conflicting_slug(sanic_client, user_headers, regular_user) -> None:
    namespace = regular_user.namespace.slug
    payload = {
        "name": "Existing project",
        "namespace": namespace,
        "slug": "my-project",
    }
    _, response = await sanic_client.post("/api/data/projects", headers=user_headers, json=payload)
    assert response.status_code == 201, response.text

    payload = {
        "name": "Conflicting project",
        "namespace": namespace,
        "slug": "my-project",
    }
    _, response = await sanic_client.post("/api/data/projects", headers=user_headers, json=payload)

    assert response.status_code == 409, response.text


@pytest.mark.asyncio
async def test_get_a_project(create_project, get_project) -> None:
    # Create some projects
    await create_project("Project 1")
    project = await create_project("Project 2")
    await create_project("Project 3")

    # Get a single project
    project = await get_project(project_id=project["id"])

    assert project["name"] == "Project 2"


@pytest.mark.asyncio
async def test_get_all_projects_with_pagination(create_project, sanic_client, user_headers) -> None:
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
async def test_default_pagination(create_project, sanic_client, user_headers) -> None:
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
async def test_pagination_with_non_existing_page(create_project, sanic_client, user_headers) -> None:
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
async def test_pagination_with_invalid_page(create_project, sanic_client, user_headers) -> None:
    parameters = {"page": 0}
    _, response = await sanic_client.get("/api/data/projects", headers=user_headers, params=parameters)

    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_pagination_with_invalid_per_page(create_project, sanic_client, user_headers) -> None:
    parameters = {"per_page": 0}
    _, response = await sanic_client.get("/api/data/projects", headers=user_headers, params=parameters)

    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_result_is_sorted_by_creation_date(create_project, sanic_client, user_headers) -> None:
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
async def test_delete_project(create_project, sanic_client, user_headers, app_config) -> None:
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

    events = await app_config.event_repo.get_pending_events()
    assert len(events) == 15
    project_removed_event = next((e for e in events if e.get_message_type() == "project.removed"), None)
    assert project_removed_event
    removed_event = deserialize_binary(
        b64decode(project_removed_event.payload["payload"]), avro_schema_v2.ProjectRemoved
    )
    assert removed_event.id == project_id

    # Get all projects
    _, response = await sanic_client.get("/api/data/projects", headers=user_headers)

    assert response.status_code == 200, response.text
    assert {p["name"] for p in response.json} == {"Project 1", "Project 2", "Project 4", "Project 5"}


@pytest.mark.asyncio
async def test_patch_project(create_project, get_project, sanic_client, user_headers, app_config) -> None:
    # Create some projects
    await create_project("Project 1")
    project = await create_project("Project 2", repositories=["http://renkulab.io/repository-0"], keywords=["keyword"])
    await create_project("Project 3")

    # Patch a project
    headers = merge_headers(user_headers, {"If-Match": project["etag"]})
    patch = {
        "name": "New Name",
        "description": "A patched Renku native project",
        "keywords": ["keyword 1", "keyword 2"],
        "visibility": "public",
        "repositories": ["http://renkulab.io/repository-1", "http://renkulab.io/repository-2"],
        "documentation": "$\\infty$",
    }
    project_id = project["id"]
    _, response = await sanic_client.patch(f"/api/data/projects/{project_id}", headers=headers, json=patch)

    assert response.status_code == 200, response.text

    events = await app_config.event_repo.get_pending_events()
    assert len(events) == 11
    project_updated_event = next((e for e in events if e.get_message_type() == "project.updated"), None)
    assert project_updated_event
    updated_event = deserialize_binary(
        b64decode(project_updated_event.payload["payload"]), avro_schema_v2.ProjectUpdated
    )
    assert updated_event.name == patch["name"]
    assert updated_event.description == patch["description"]
    assert updated_event.repositories == patch["repositories"]

    # Get the project
    project = await get_project(project_id=project_id)

    assert project["name"] == "New Name"
    assert project["slug"] == "project-2"
    assert project["description"] == "A patched Renku native project"
    assert set(project["keywords"]) == {"keyword 1", "keyword 2"}
    assert project["visibility"] == "public"
    assert {r for r in project["repositories"]} == {
        "http://renkulab.io/repository-1",
        "http://renkulab.io/repository-2",
    }
    assert "documentation" not in project

    _, response = await sanic_client.get(
        f"/api/data/projects/{project_id}", params={"with_documentation": True}, headers=user_headers
    )

    assert response.status_code == 200, response.text
    project = response.json
    assert project["documentation"] == "$\\infty$"


@pytest.mark.asyncio
async def test_keywords_are_not_modified_in_patch(
    create_project, get_project, sanic_client, user_headers, app_config
) -> None:
    # Create some projects
    await create_project("Project 1")
    project = await create_project("Project 2", keywords=["keyword 1", "keyword 2"])
    await create_project("Project 3")

    # Patch a project
    user_headers.update({"If-Match": project["etag"]})
    patch_no_keywords = {"name": "New Name"}
    project_id = project["id"]
    _, response = await sanic_client.patch(
        f"/api/data/projects/{project_id}", headers=user_headers, json=patch_no_keywords
    )

    assert response.status_code == 200, response.text

    # Get the project
    project = await get_project(project_id=project_id)

    assert set(project["keywords"]) == {"keyword 1", "keyword 2"}


@pytest.mark.asyncio
async def test_keywords_are_deleted_in_patch(
    create_project, get_project, sanic_client, user_headers, app_config
) -> None:
    # Create some projects
    await create_project("Project 1")
    project = await create_project("Project 2", keywords=["keyword 1", "keyword 2"])
    await create_project("Project 3")

    # Patch a project
    user_headers.update({"If-Match": project["etag"]})
    patch_with_empty_keywords = {
        "name": "New Name",
        "keywords": [],
    }
    project_id = project["id"]
    _, response = await sanic_client.patch(
        f"/api/data/projects/{project_id}", headers=user_headers, json=patch_with_empty_keywords
    )

    assert response.status_code == 200, response.text

    # Get the project
    project = await get_project(project_id=project_id)

    assert len(project["keywords"]) == 0


@pytest.mark.asyncio
async def test_patch_visibility_to_private_hides_project(
    create_project, admin_headers, sanic_client, user_headers
) -> None:
    project = await create_project("Project 1", admin=True, visibility="public")

    _, response = await sanic_client.get("/api/data/projects", headers=user_headers)
    assert response.json[0]["name"] == "Project 1"

    headers = merge_headers(admin_headers, {"If-Match": project["etag"]})
    patch = {
        "visibility": "private",
    }
    project_id = project["id"]
    _, response = await sanic_client.patch(f"/api/data/projects/{project_id}", headers=headers, json=patch)
    assert response.status_code == 200, response.text

    _, response = await sanic_client.get("/api/data/projects", headers=user_headers)

    assert len(response.json) == 0


@pytest.mark.asyncio
async def test_patch_visibility_to_public_shows_project(
    create_project, admin_headers, sanic_client, user_headers
) -> None:
    project = await create_project("Project 1", admin=True, visibility="private")

    _, response = await sanic_client.get("/api/data/projects", headers=user_headers)
    assert len(response.json) == 0

    headers = merge_headers(admin_headers, {"If-Match": project["etag"]})
    patch = {
        "visibility": "public",
    }
    project_id = project["id"]
    _, response = await sanic_client.patch(f"/api/data/projects/{project_id}", headers=headers, json=patch)
    assert response.status_code == 200, response.text

    _, response = await sanic_client.get("/api/data/projects", headers=user_headers)

    assert response.json[0]["name"] == "Project 1"


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["id", "slug", "created_by", "creation_date"])
async def test_cannot_patch_reserved_fields(create_project, get_project, sanic_client, user_headers, field) -> None:
    project = await create_project("Project 1")
    original_value = project[field]

    # Try to patch the project
    headers = merge_headers(user_headers, {"If-Match": project["etag"]})
    patch = {
        field: "new-value",
    }
    project_id = project["id"]
    _, response = await sanic_client.patch(f"/api/data/projects/{project_id}", headers=headers, json=patch)

    assert response.status_code == 422
    assert f"{field}: Extra inputs are not permitted" in response.text

    # Check that the field's value didn't change
    project = await get_project(project_id=project_id)

    assert project[field] == original_value


@pytest.mark.asyncio
async def test_cannot_patch_without_if_match_header(create_project, get_project, sanic_client, user_headers) -> None:
    project = await create_project("Project 1")
    original_value = project["name"]

    # Try to patch the project
    patch = {
        "name": "New Name",
    }
    project_id = project["id"]
    _, response = await sanic_client.patch(f"/api/data/projects/{project_id}", headers=user_headers, json=patch)

    assert response.status_code == 428
    assert "If-Match header not provided" in response.text

    # Check that the field's value didn't change
    project = await get_project(project_id=project_id)

    assert project["name"] == original_value


@pytest.mark.asyncio
async def test_patch_project_invalid_namespace(
    create_project, sanic_client, user_headers, member_1_user: UserInfo
) -> None:
    namespace = member_1_user.namespace.slug
    _, response = await sanic_client.get(f"/api/data/namespaces/{namespace}", headers=user_headers)
    assert response.status_code == 200, response.text
    project = await create_project("Project 1")

    # Patch a project
    headers = merge_headers(user_headers, {"If-Match": project["etag"]})
    patch = {
        "namespace": namespace,
    }
    project_id = project["id"]
    _, response = await sanic_client.patch(f"/api/data/projects/{project_id}", headers=headers, json=patch)

    assert response.status_code == 403, response.text
    assert "you do not have sufficient permissions" in response.json["error"]["message"]


@pytest.mark.asyncio
async def test_patch_description_as_editor_and_keep_namespace_and_visibility(
    sanic_client,
    create_project,
    user_headers,
    regular_user,
) -> None:
    project = await create_project("Project 1", admin=True, members=[{"id": regular_user.id, "role": "editor"}])
    project_id = project["id"]

    headers = merge_headers(user_headers, {"If-Match": project["etag"]})
    patch = {
        # Test that we do not require DELETE permission when sending the current namespace
        "namespace": project["namespace"],
        # Test that we do not require DELETE permission when sending the current visibility
        "visibility": project["visibility"],
        "description": "Updated description",
    }
    _, response = await sanic_client.patch(f"/api/data/projects/{project_id}", headers=headers, json=patch)

    assert response.status_code == 200, response.text
    assert response.json is not None
    assert response.json.get("namespace") == project["namespace"]
    assert response.json.get("visibility") == project["visibility"]
    assert response.json.get("description") == "Updated description"


@pytest.mark.asyncio
async def test_get_all_projects_for_specific_user(
    create_project, sanic_client, user_headers, admin_headers, unauthorized_headers
) -> None:
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
async def test_get_projects_with_namespace_filter(create_project, sanic_client, user_headers) -> None:
    await create_project("Project 1", visibility="private")
    await create_project("Project 2", visibility="public")
    await create_project("Project 3", admin=True, visibility="private")
    await create_project("Project 4", admin=True, visibility="public")

    _, response = await sanic_client.get("/api/data/projects", headers=user_headers)

    assert response.status_code == 200, response.text
    projects = response.json
    assert {p["name"] for p in projects} == {"Project 1", "Project 2", "Project 4"}

    _, response = await sanic_client.get("/api/data/projects?namespace=user.doe", headers=user_headers)
    assert response.status_code == 200, response.text
    projects = response.json
    assert {p["name"] for p in projects} == {"Project 1", "Project 2"}

    _, response = await sanic_client.get("/api/data/projects?namespace=admin.doe", headers=user_headers)
    assert response.status_code == 200, response.text
    projects = response.json
    assert {p["name"] for p in projects} == {"Project 4"}


@pytest.mark.asyncio
async def test_get_projects_with_direct_membership(sanic_client, user_headers, member_1_headers, member_1_user) -> None:
    # Create a group
    namespace = "my-group"
    payload = {
        "name": "Group",
        "slug": namespace,
    }
    _, response = await sanic_client.post("/api/data/groups", headers=user_headers, json=payload)
    assert response.status_code == 201, response.text
    # Create some projects in the group
    payload = {
        "name": "Project 1",
        "namespace": namespace,
    }
    _, response = await sanic_client.post("/api/data/projects", headers=user_headers, json=payload)
    assert response.status_code == 201, response.text
    project_1 = response.json
    payload = {
        "name": "Project 2",
        "namespace": namespace,
    }
    _, response = await sanic_client.post("/api/data/projects", headers=user_headers, json=payload)
    assert response.status_code == 201, response.text
    project_2 = response.json
    # Add member_1 to the group
    roles = [{"id": member_1_user.id, "role": "editor"}]
    _, response = await sanic_client.patch(f"/api/data/groups/{namespace}/members", headers=user_headers, json=roles)
    assert response.status_code == 200, response.text
    # Add member_1 to Project 2
    roles = [{"id": member_1_user.id, "role": "editor"}]
    _, response = await sanic_client.patch(
        f"/api/data/projects/{project_2["id"]}/members", headers=user_headers, json=roles
    )
    assert response.status_code == 200, response.text

    parameters = {"direct_member": True}
    _, response = await sanic_client.get("/api/data/projects", headers=member_1_headers, params=parameters)

    assert response.status_code == 200, response.text
    projects = response.json
    assert len(projects) == 1
    project_ids = {p["id"] for p in projects}
    assert project_ids == {project_2["id"]}

    # Check that both projects can be seen without the filter
    _, response = await sanic_client.get("/api/data/projects", headers=member_1_headers)
    projects = response.json
    assert len(projects) == 2
    project_ids = {p["id"] for p in projects}
    assert project_ids == {project_1["id"], project_2["id"]}


@pytest.mark.asyncio
async def test_unauthorized_user_cannot_create_delete_or_modify_projects(
    create_project, sanic_client, unauthorized_headers
) -> None:
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
async def test_creator_is_added_as_owner_members(sanic_client, create_project, user_headers) -> None:
    project = await create_project("project-name")
    project_id = project["id"]

    _, response = await sanic_client.get(f"/api/data/projects/{project_id}/members", headers=user_headers)

    assert response.status_code == 200, response.text

    assert len(response.json) == 1
    member = response.json[0]
    assert member == {"id": "user", "first_name": "User", "last_name": "Doe", "role": "owner", "namespace": "user.doe"}


@pytest.mark.asyncio
async def test_add_project_members(
    create_project,
    sanic_client,
    regular_user,
    user_headers,
    app_config,
    member_1_user: UserInfo,
    member_2_user: UserInfo,
) -> None:
    project = await create_project("Project 1")
    project_id = project["id"]

    # Add new roles
    members = [{"id": member_1_user.id, "role": "viewer"}, {"id": member_2_user.id, "role": "owner"}]
    _, response = await sanic_client.patch(
        f"/api/data/projects/{project_id}/members", headers=user_headers, json=members
    )
    assert response.status_code == 200, response.text

    # Check that you can see the new roles
    _, response = await sanic_client.get(f"/api/data/projects/{project_id}/members", headers=user_headers)
    assert response.status_code == 200, response.text
    assert len(response.json) == 3
    member = next(m for m in response.json if m["id"] == "user")
    assert member["role"] == "owner"
    member = next(m for m in response.json if m["id"] == "member-1")
    assert member["role"] == "viewer"
    member = next(m for m in response.json if m["id"] == "member-2")
    assert member["role"] == "owner"

    # Check that patching the same role with itself and truly changing another role produces only 1 update
    members = [{"id": "member-1", "role": "owner"}, {"id": "member-2", "role": "owner"}]
    _, response = await sanic_client.patch(
        f"/api/data/projects/{project_id}/members", headers=user_headers, json=members
    )
    assert response.status_code == 200, response.text
    _, response = await sanic_client.get(
        f"/api/data/projects/{project_id}/members",
        headers=user_headers,
    )
    assert len(response.json) == 3


@pytest.mark.asyncio
async def test_delete_project_members(create_project, sanic_client, user_headers, app_config: Config) -> None:
    project = await create_project("Project 1")
    project_id = project["id"]

    members = [{"id": "member-1", "role": "viewer"}, {"id": "member-2", "role": "viewer"}]
    await sanic_client.patch(f"/api/data/projects/{project_id}/members", headers=user_headers, json=members)

    _, response = await sanic_client.delete(f"/api/data/projects/{project_id}/members/member-1", headers=user_headers)

    assert response.status_code == 204, response.text

    _, response = await sanic_client.get(f"/api/data/projects/{project_id}/members", headers=user_headers)

    assert response.status_code == 200, response.text

    assert len(response.json) == 2
    assert {
        "id": "user",
        "first_name": "User",
        "last_name": "Doe",
        "role": "owner",
        "namespace": "user.doe",
    } in response.json


@pytest.mark.asyncio
async def test_null_byte_middleware(sanic_client, user_headers, regular_user, app_config) -> None:
    payload = {
        "name": "Renku Native \x00Project",
        "slug": "project-slug",
        "description": "First Renku native project",
        "visibility": "public",
        "repositories": ["http://renkulab.io/repository-1", "http://renkulab.io/repository-2"],
        "namespace": f"{regular_user.first_name}.{regular_user.last_name}",
    }

    _, response = await sanic_client.post("/api/data/projects", headers=user_headers, json=payload)

    assert response.status_code == 422, response.text
    assert "Null byte found in request" in response.text


@pytest.mark.asyncio
async def test_cannot_change_membership_non_existent_resources(create_project, sanic_client, user_headers) -> None:
    project = await create_project("Project 1")
    project_id = project["id"]

    # User does not exist
    members = [{"id": "non-existing", "role": "viewer"}]
    _, response = await sanic_client.patch(
        f"/api/data/projects/{project_id}/members", headers=user_headers, json=members
    )
    assert response.status_code == 404

    # Project does not exist
    non_existent_project_id = str(ULID())
    members = [{"id": "member-1", "role": "viewer"}]
    _, response = await sanic_client.patch(
        f"/api/data/projects/{non_existent_project_id}/members", headers=user_headers, json=members
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_project_owner_cannot_remove_themselves_if_no_other_owner(
    create_project,
    sanic_client,
    user_headers,
    regular_user: UserInfo,
    member_1_user: UserInfo,
    member_1_headers: dict,
) -> None:
    owner = regular_user
    project = await create_project("Project 1")
    project_id = project["id"]
    assert project["created_by"] == owner.id

    # Try to remove the only owner
    _, response = await sanic_client.delete(f"/api/data/projects/{project_id}/members/{owner.id}", headers=user_headers)
    assert response.status_code == 422

    # Add another user as the owner
    members = [{"id": member_1_user.id, "role": "owner"}]
    _, response = await sanic_client.patch(
        f"/api/data/projects/{project_id}/members", headers=user_headers, json=members
    )
    assert response.status_code == 200

    # Now an owner can remove themselves
    _, response = await sanic_client.delete(f"/api/data/projects/{project_id}/members/{owner.id}", headers=user_headers)
    assert response.status_code == 204
    _, response = await sanic_client.get(f"/api/data/projects/{project_id}/members", headers=member_1_headers)
    assert response.status_code == 200
    assert len(response.json) == 1
    assert response.json[0]["id"] == member_1_user.id


@pytest.mark.asyncio
async def test_cannot_change_role_for_last_project_owner(
    create_project, sanic_client, user_headers, regular_user: UserInfo, member_1_headers
) -> None:
    project = await create_project("Project 1")
    project_id = project["id"]

    # Cannot change the role of the last project owner
    members = [{"id": regular_user.id, "role": "editor"}]
    _, response = await sanic_client.patch(
        f"/api/data/projects/{project_id}/members", headers=user_headers, json=members
    )
    assert response.status_code == 422

    # Can change the owner role if another owner is added during an update
    members.append({"id": "member-1", "role": "owner"})
    _, response = await sanic_client.patch(
        f"/api/data/projects/{project_id}/members", headers=user_headers, json=members
    )

    assert response.status_code == 200

    # Add another owner and then check that cannot remove both owners
    members = [{"id": regular_user.id, "role": "owner"}]
    _, response = await sanic_client.patch(
        f"/api/data/projects/{project_id}/members", headers=member_1_headers, json=members
    )
    assert response.status_code == 200

    members = [{"id": regular_user.id, "role": "editor"}, {"id": "member-1", "role": "editor"}]
    _, response = await sanic_client.patch(
        f"/api/data/projects/{project_id}/members", headers=member_1_headers, json=members
    )

    assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["viewer", "editor", "owner"])
async def test_get_project_permissions(sanic_client, create_project, user_headers, regular_user, role) -> None:
    project = await create_project("Project 1", admin=True, members=[{"id": regular_user.id, "role": role}])
    project_id = project["id"]

    expected_permissions = dict(
        write=False,
        delete=False,
        change_membership=False,
    )
    if role == "editor" or role == "owner":
        expected_permissions["write"] = True
    if role == "owner":
        expected_permissions["delete"] = True
        expected_permissions["change_membership"] = True

    _, response = await sanic_client.get(f"/api/data/projects/{project_id}/permissions", headers=user_headers)

    assert response.status_code == 200, response.text
    assert response.json is not None
    permissions = response.json
    assert permissions.get("write") == expected_permissions["write"]
    assert permissions.get("delete") == expected_permissions["delete"]
    assert permissions.get("change_membership") == expected_permissions["change_membership"]


@pytest.mark.asyncio
async def test_get_project_permissions_unauthorized(sanic_client, create_project, user_headers) -> None:
    project = await create_project("Project 1", admin=True)
    project_id = project["id"]

    _, response = await sanic_client.get(f"/api/data/projects/{project_id}/permissions", headers=user_headers)

    assert response.status_code == 404, response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["viewer", "editor", "owner"])
async def test_get_project_permissions_cascading_from_group(
    sanic_client, admin_headers, user_headers, regular_user, role
) -> None:
    _, response = await sanic_client.post(
        "/api/data/groups", headers=admin_headers, json={"name": "My Group", "slug": "my-group"}
    )
    assert response.status_code == 201, response.text
    patch = [{"id": regular_user.id, "role": role}]
    _, response = await sanic_client.patch("/api/data/groups/my-group/members", headers=admin_headers, json=patch)
    assert response.status_code == 200, response.text
    _, response = await sanic_client.post(
        "/api/data/projects", headers=admin_headers, json={"name": "My project", "namespace": "my-group"}
    )
    assert response.status_code == 201, response.text
    project = response.json
    project_id = project["id"]

    expected_permissions = dict(
        write=False,
        delete=False,
        change_membership=False,
    )
    if role == "editor" or role == "owner":
        expected_permissions["write"] = True
    if role == "owner":
        expected_permissions["delete"] = True
        expected_permissions["change_membership"] = True

    _, response = await sanic_client.get(f"/api/data/projects/{project_id}/permissions", headers=user_headers)

    assert response.status_code == 200, response.text
    assert response.json is not None
    permissions = response.json
    assert permissions.get("write") == expected_permissions["write"]
    assert permissions.get("delete") == expected_permissions["delete"]
    assert permissions.get("change_membership") == expected_permissions["change_membership"]


@pytest.mark.asyncio
async def test_project_slug_case(
    app_config: Config,
    create_project,
    create_group,
    sanic_client,
    user_headers,
) -> None:
    from renku_data_services.project.orm import ProjectORM

    group = await create_group("group1")
    project = await create_project("Project 1", namespace=group["slug"], slug="project-1")
    project_id = project["id"]
    # Cannot create projects with upper case slug
    payload = {
        "name": "Normal project",
        "namespace": group["slug"],
    }
    _, res = await sanic_client.post("/api/data/projects", json=payload, headers=user_headers)
    assert res.status_code == 201
    payload["slug"] = "SlugWithUppercase"
    _, res = await sanic_client.post("/api/data/projects", json=payload, headers=user_headers)
    assert res.status_code == 422
    # Cannot patch the project with upper case slug
    payload = {"slug": "sOmEsLuG"}
    if_match_headers = {"If-Match": "*"}
    _, res = await sanic_client.patch(
        f"/api/data/projects/{project_id}", json=payload, headers={**if_match_headers, **user_headers}
    )
    assert res.status_code == 422
    # Change the slug of the project to be upper case in the DB
    uppercase_slug = "NEW_project_SLUG"
    async with app_config.db.async_session_maker() as session, session.begin():
        stmt = select(ProjectORM).where(ProjectORM.id == project_id)
        proj_orm = await session.scalar(stmt)
        assert proj_orm is not None
        proj_orm.slug.slug = uppercase_slug
    # You should still be able to do everything to this project now
    # Get the project
    _, res = await sanic_client.get(f"/api/data/projects/{project_id}", headers=user_headers)
    assert res.status_code == 200
    assert res.json.get("slug") == uppercase_slug
    etag = res.headers["ETag"]
    # Get it by the namespace
    _, res = await sanic_client.get(
        f"/api/data/namespaces/{group['slug']}/projects/{uppercase_slug}", headers=user_headers
    )
    assert res.status_code == 200
    assert res.json.get("slug") == uppercase_slug
    # Patch the project
    new_name = "new-name"
    _, res = await sanic_client.patch(
        f"/api/data/projects/{project_id}",
        json={"name": new_name},
        headers={"If-Match": etag, **user_headers},
    )
    assert res.status_code == 200
    assert res.json["slug"] == uppercase_slug
    assert res.json["name"] == new_name


@pytest.mark.asyncio
async def test_project_copy_basics(sanic_client, app_config, user_headers, regular_user, create_project) -> None:
    await create_project("Project 1")
    project = await create_project(
        "Project 2",
        description="template project",
        keywords=["tag 1", "tag 2"],
        repositories=["http://repository-1.ch", "http://repository-2.ch"],
        visibility="public",
    )
    await create_project("Project 3")
    project_id = project["id"]

    payload = {
        "name": "Renku Native Project",
        "slug": "project-slug",
        "namespace": regular_user.namespace.slug,
    }

    await app_config.event_repo.delete_all_events()

    _, response = await sanic_client.post(f"/api/data/projects/{project_id}/copies", headers=user_headers, json=payload)

    assert response.status_code == 201, response.text
    copy_project = response.json
    assert copy_project["name"] == "Renku Native Project"
    assert copy_project["slug"] == "project-slug"
    assert copy_project["created_by"] == "user"
    assert copy_project["namespace"] == regular_user.namespace.slug
    assert copy_project["description"] == "template project"
    assert copy_project["visibility"] == project["visibility"]
    assert copy_project["keywords"] == ["tag 1", "tag 2"]
    assert copy_project["repositories"] == project["repositories"]

    events = await app_config.event_repo.get_pending_events()
    assert len(events) == 2
    project_created_event = next(e for e in events if e.get_message_type() == "project.created")
    project_created = deserialize_event(project_created_event)
    assert project_created.name == payload["name"]
    assert project_created.slug == payload["slug"]
    assert project_created.repositories == project["repositories"]
    project_auth_added_event = next(e for e in events if e.get_message_type() == "projectAuth.added")
    project_auth_added = deserialize_event(project_auth_added_event)
    assert project_auth_added.userId == "user"
    assert project_auth_added.role == MemberRole.OWNER

    project_id = copy_project["id"]

    _, response = await sanic_client.get(f"/api/data/projects/{project_id}", headers=user_headers)

    assert response.status_code == 200, response.text
    copy_project = response.json
    assert copy_project["name"] == "Renku Native Project"
    assert copy_project["slug"] == "project-slug"
    assert copy_project["created_by"] == "user"
    assert copy_project["namespace"] == regular_user.namespace.slug
    assert copy_project["description"] == "template project"
    assert copy_project["visibility"] == "public"
    assert copy_project["keywords"] == ["tag 1", "tag 2"]
    assert copy_project["repositories"] == ["http://repository-1.ch", "http://repository-2.ch"]


@pytest.mark.asyncio
async def test_project_copy_includes_session_launchers(
    sanic_client,
    user_headers,
    regular_user,
    create_project,
    create_session_environment,
    create_session_launcher,
    create_project_copy,
) -> None:
    project = await create_project("Project")
    project_id = project["id"]
    environment = await create_session_environment("Some environment")
    launcher_1 = await create_session_launcher("Launcher 1", project["id"], environment={"id": environment["id"]})
    launcher_2 = await create_session_launcher("Launcher 2", project["id"], environment={"id": environment["id"]})

    copy_project = await create_project_copy(project_id, regular_user.namespace.slug, "Copy Project")
    project_id = copy_project["id"]
    _, response = await sanic_client.get(f"/api/data/projects/{project_id}/session_launchers", headers=user_headers)

    assert response.status_code == 200, response.text
    launchers = response.json
    assert {launcher["name"] for launcher in launchers} == {"Launcher 1", "Launcher 2"}
    assert launchers[0]["project_id"] == launchers[1]["project_id"] == project_id
    # NOTE: Check that new launchers are created
    assert {launcher["id"] for launcher in launchers} != {launcher_1["id"], launcher_2["id"]}


@pytest.mark.asyncio
async def test_project_copy_includes_data_connector_links(
    sanic_client,
    user_headers,
    regular_user,
    create_project,
    create_data_connector_and_link_project,
    create_project_copy,
) -> None:
    project = await create_project("Project")
    project_id = project["id"]
    data_connector_1, link_1 = await create_data_connector_and_link_project("Data Connector 1", project_id=project_id)
    data_connector_2, link_2 = await create_data_connector_and_link_project("Data Connector 2", project_id=project_id)

    copy_project = await create_project_copy(project_id, regular_user.namespace.slug, "Copy Project")
    project_id = copy_project["id"]
    _, response = await sanic_client.get(f"/api/data/projects/{project_id}/data_connector_links", headers=user_headers)

    assert response.status_code == 200, response.text
    data_connector_links = response.json
    assert {d["data_connector_id"] for d in data_connector_links} == {data_connector_1["id"], data_connector_2["id"]}
    assert data_connector_links[0]["project_id"] == data_connector_links[1]["project_id"] == project_id
    # NOTE: Check that new data connector links are created
    assert {d["id"] for d in data_connector_links} != {link_1["id"], link_2["id"]}


@pytest.mark.asyncio
async def test_project_get_all_copies(
    sanic_client, regular_user, user_headers, create_project, create_project_copy
) -> None:
    await create_project("Project 1")
    project = await create_project("Project 2")
    await create_project("Project 3")
    project_id = project["id"]

    copy_1 = await create_project_copy(project_id, regular_user.namespace.slug, "Copy 1")
    copy_2 = await create_project_copy(project_id, regular_user.namespace.slug, "Copy 2")

    _, response = await sanic_client.get(f"/api/data/projects/{project_id}/copies", headers=user_headers)

    assert response.status_code == 200, response.text
    copies = response.json
    assert len(copies) == 2
    assert {c["id"] for c in copies} == {copy_1["id"], copy_2["id"]}


@pytest.mark.asyncio
async def test_project_copies_are_not_deleted_when_template_is_deleted(
    sanic_client, regular_user, user_headers, create_project, create_project_copy
) -> None:
    project = await create_project("Template Project")
    project_id = project["id"]

    copy_1 = await create_project_copy(project_id, regular_user.namespace.slug, "Copy 1")
    copy_2 = await create_project_copy(project_id, regular_user.namespace.slug, "Copy 2")

    _, response = await sanic_client.delete(f"/api/data/projects/{project_id}", headers=user_headers)

    _, response = await sanic_client.get("/api/data/projects", headers=user_headers)

    assert response.status_code == 200, response.text
    copies = response.json
    assert {p["id"] for p in copies} == {copy_1["id"], copy_2["id"]}
    assert "template_id" not in copies[0]
    assert "template_id" not in copies[1]


@pytest.mark.asyncio
async def test_project_copy_and_set_visibility(
    sanic_client, regular_user, user_headers, create_project, create_project_copy
) -> None:
    project = await create_project("Template Project")
    project_id = project["id"]

    public_copy = await create_project_copy(project_id, regular_user.namespace.slug, "Copy 1", visibility="public")
    private_copy = await create_project_copy(project_id, regular_user.namespace.slug, "Copy 2", visibility="private")

    _, response = await sanic_client.get("/api/data/projects", headers=user_headers)

    assert response.status_code == 200, response.text
    copies = response.json
    assert next(c for c in copies if c["id"] == public_copy["id"])["visibility"] == "public"
    assert next(c for c in copies if c["id"] == private_copy["id"])["visibility"] == "private"


@pytest.mark.asyncio
async def test_project_copy_non_existing_project(sanic_client, user_headers, regular_user, create_project) -> None:
    await create_project("Project 1")
    project_id = "01JC3CB5426KC7P5STS5X3KSS8"
    payload = {
        "name": "Renku Native Project",
        "slug": "project-slug",
        "namespace": regular_user.namespace.slug,
    }

    _, response = await sanic_client.post(f"/api/data/projects/{project_id}/copies", headers=user_headers, json=payload)

    assert response.status_code == 404
    assert "does not exist or you do not have access to it" in response.text


@pytest.mark.asyncio
async def test_project_copy_invalid_project_id(sanic_client, user_headers, regular_user, create_project) -> None:
    await create_project("Project 1")
    project_id = "Invalid-ULID-project-id"
    payload = {
        "name": "Renku Native Project",
        "slug": "project-slug",
        "namespace": regular_user.namespace.slug,
    }

    _, response = await sanic_client.post(f"/api/data/projects/{project_id}/copies", headers=user_headers, json=payload)

    assert response.status_code == 422
    assert "Template project ID isn't valid" in response.text


@pytest.mark.asyncio
async def test_project_copy_with_no_access(sanic_client, user_headers, regular_user, create_project) -> None:
    project = await create_project("Project 1", admin=True)
    project_id = project["id"]
    payload = {
        "name": "Renku Native Project",
        "slug": "project-slug",
        "namespace": regular_user.namespace.slug,
    }

    _, response = await sanic_client.post(f"/api/data/projects/{project_id}/copies", headers=user_headers, json=payload)

    assert response.status_code == 404
    assert "does not exist or you do not have access to it" in response.text


@pytest.mark.asyncio
async def test_project_copy_succeeds_even_if_data_connector_is_inaccessible(
    sanic_client,
    user_headers,
    regular_user,
    create_project,
    create_session_environment,
    create_session_launcher,
    create_project_copy,
    create_data_connector_and_link_project
) -> None:
    project = await create_project("Project")
    project_id = project["id"]
    environment = await create_session_environment("Environment")
    launcher = await create_session_launcher("Launcher", project["id"], environment={"id": environment["id"]})
    # NOTE: Create a data connector that regular user cannot access
    _, _ = await create_data_connector_and_link_project("Connector", project_id=project_id, admin=True)

    payload = {
        "name": "Copy Project",
        "slug": "project-slug",
        "namespace": regular_user.namespace.slug,
    }

    _, response = await sanic_client.post(f"/api/data/projects/{project_id}/copies", headers=user_headers, json=payload)

    # NOTE: The copy is created, but the status code indicates that one of the multiple statuses is a failure
    assert response.status_code == 207, response.text

    copy_project = response.json
    project_id = copy_project["id"]
    _, response = await sanic_client.get(f"/api/data/projects/{project_id}/session_launchers", headers=user_headers)

    assert response.status_code == 200, response.text
    launchers = response.json
    assert {launcher["name"] for launcher in launchers} == {"Launcher"}
    assert launchers[0]["project_id"] == project_id
    # NOTE: Check that a new launcher is created
    assert launchers[0]["id"] != launcher["id"]
