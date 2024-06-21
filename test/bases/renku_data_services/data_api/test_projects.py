"""Tests for projects blueprint."""

import time
from base64 import b64decode
from typing import Any

import pytest
from ulid import ULID

from components.renku_data_services.message_queue.avro_models.io.renku.events import v2 as avro_schema_v2
from renku_data_services.app_config.config import Config
from renku_data_services.message_queue.avro_models.io.renku.events.v2.member_role import MemberRole
from renku_data_services.message_queue.models import deserialize_binary
from renku_data_services.users.models import UserInfo
from test.bases.renku_data_services.data_api.utils import merge_headers


@pytest.fixture
def create_project(sanic_client, user_headers, admin_headers, regular_user, admin_user, bootstrap_admins):
    async def create_project_helper(name: str, admin: bool = False, **payload) -> dict[str, Any]:
        headers = admin_headers if admin else user_headers
        user = admin_user if admin else regular_user
        payload = payload.copy()
        payload.update({"name": name, "namespace": f"{user.first_name}.{user.last_name}"})

        _, response = await sanic_client.post("/api/data/projects", headers=headers, json=payload)

        assert response.status_code == 201, response.text
        return response.json

    return create_project_helper


@pytest.fixture
def get_project(sanic_client, user_headers, admin_headers):
    async def get_project_helper(project_id: str, admin: bool = False) -> dict[str, Any]:
        headers = admin_headers if admin else user_headers
        _, response = await sanic_client.get(f"/api/data/projects/{project_id}", headers=headers)

        assert response.status_code == 200, response.text
        return response.json

    return get_project_helper


@pytest.mark.asyncio
async def test_project_creation(sanic_client, user_headers, regular_user, app_config) -> None:
    payload = {
        "name": "Renku Native Project",
        "slug": "project-slug",
        "description": "First Renku native project",
        "visibility": "public",
        "repositories": ["http://renkulab.io/repository-1", "http://renkulab.io/repository-2"],
        "namespace": f"{regular_user.first_name}.{regular_user.last_name}",
        "keywords": ["keyword 1", "keyword.2", "keyword-3", "KEYWORD_4"],
    }

    _, response = await sanic_client.post("/api/data/projects", headers=user_headers, json=payload)

    assert response.status_code == 201, response.text
    project = response.json
    assert project["name"] == "Renku Native Project"
    assert project["slug"] == "project-slug"
    assert project["description"] == "First Renku native project"
    assert set(project["keywords"]) == {"keyword 1", "keyword.2", "keyword-3", "KEYWORD_4"}
    assert project["visibility"] == "public"
    assert project["created_by"] == "user"
    assert {r for r in project["repositories"]} == {
        "http://renkulab.io/repository-1",
        "http://renkulab.io/repository-2",
    }
    project_id = project["id"]

    events = await app_config.event_repo._get_pending_events()
    assert len(events) == 6
    project_created_event = next((e for e in events if e.queue == "project.created"), None)
    assert project_created_event
    created_event = deserialize_binary(
        b64decode(project_created_event.payload["payload"]), avro_schema_v2.ProjectCreated
    )
    assert created_event.name == payload["name"]
    assert created_event.slug == payload["slug"]
    assert created_event.repositories == payload["repositories"]
    project_auth_added = next((e for e in events if e.queue == "projectAuth.added"), None)
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
    assert set(project["keywords"]) == {"keyword 1", "keyword.2", "keyword-3", "KEYWORD_4"}
    assert project["visibility"] == "public"
    assert project["created_by"] == "user"
    assert {r for r in project["repositories"]} == {
        "http://renkulab.io/repository-1",
        "http://renkulab.io/repository-2",
    }

    # same as above, but using namespace/slug to retreive the pr
    _, response = await sanic_client.get(
        f"/api/data/projects/{payload['namespace']}/{payload['slug']}", headers=user_headers
    )

    assert response.status_code == 200, response.text
    project = response.json
    assert project["name"] == "Renku Native Project"
    assert project["slug"] == "project-slug"
    assert project["namespace"] == f"{regular_user.first_name.lower()}.{regular_user.last_name.lower()}"


@pytest.mark.asyncio
async def test_project_creation_with_default_values(sanic_client, user_headers, regular_user, get_project) -> None:
    payload = {
        "name": "Project with Default Values",
        "namespace": f"{regular_user.first_name}.{regular_user.last_name}",
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

    events = await app_config.event_repo._get_pending_events()
    assert len(events) == 15
    project_removed_event = next((e for e in events if e.queue == "project.removed"), None)
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
    }
    project_id = project["id"]
    _, response = await sanic_client.patch(f"/api/data/projects/{project_id}", headers=headers, json=patch)

    assert response.status_code == 200, response.text

    events = await app_config.event_repo._get_pending_events()
    assert len(events) == 11
    project_updated_event = next((e for e in events if e.queue == "project.updated"), None)
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
    assert member == {
        "id": "user",
        "email": "user.doe@gmail.com",
        "first_name": "User",
        "last_name": "Doe",
        "role": "owner",
    }


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
        "email": "user.doe@gmail.com",
        "first_name": "User",
        "last_name": "Doe",
        "role": "owner",
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
    assert response.status_code == 401

    # Add another user as owner
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
    assert response.status_code == 401

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

    assert response.status_code == 401
