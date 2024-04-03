import json
from datetime import datetime
from test.bases.renku_data_services.keycloak_sync.test_sync import get_kc_users

import pytest
import pytest_asyncio
from sanic import Sanic
from sanic_testing.testing import SanicASGITestClient

from renku_data_services.app_config import Config
from renku_data_services.data_api.app import register_all_handlers
from renku_data_services.users.dummy_kc_api import DummyKeycloakAPI
from renku_data_services.users.models import UserInfo


@pytest.fixture
def admin_user() -> UserInfo:
    return UserInfo("admin", "Admin", "Doe", "admin.doe@gmail.com")


@pytest.fixture
def regular_user() -> UserInfo:
    return UserInfo("user", "User", "Doe", "user.doe@gmail.com")


@pytest.fixture
def users(regular_user, admin_user) -> list[UserInfo]:
    return [
        regular_user,
        admin_user,
        UserInfo("member-1", "Member-1", "Doe", "member-1.doe@gmail.com"),
        UserInfo("member-2", "Member-2", "Doe", "member-2.doe@gmail.com"),
    ]


@pytest_asyncio.fixture
async def sanic_client(app_config: Config, users: list[UserInfo]) -> SanicASGITestClient:
    app_config.kc_api = DummyKeycloakAPI(users=get_kc_users(users))
    app = Sanic(app_config.app_name)
    app = register_all_handlers(app, app_config)
    await app_config.kc_user_repo.initialize(app_config.kc_api)
    await app_config.group_repo.generate_user_namespaces()
    return SanicASGITestClient(app)


@pytest.fixture
def admin_headers(admin_user) -> dict[str, str]:
    """Authentication headers for an admin user."""
    access_token = json.dumps(
        {"is_admin": True, "id": admin_user.id, "name": f"{admin_user.first_name} {admin_user.last_name}"}
    )
    return {"Authorization": f"Bearer {access_token}"}


@pytest.fixture
def user_headers(regular_user: UserInfo) -> dict[str, str]:
    """Authentication headers for a normal user."""
    access_token = json.dumps(
        {"is_admin": False, "id": regular_user.id, "name": f"{regular_user.first_name} {regular_user.last_name}"}
    )
    return {"Authorization": f"Bearer {access_token}"}


@pytest.fixture
def unauthorized_headers() -> dict[str, str]:
    """Authentication headers for an anonymous user (did not log in)."""
    return {"Authorization": "Bearer {}"}


@pytest.mark.asyncio
async def test_group_creation_basic(sanic_client, user_headers):
    payload = {
        "name": "Group1",
        "slug": "group-1",
        "description": "Group 1 Description",
    }

    _, response = await sanic_client.post("/api/data/groups", headers=user_headers, json=payload)

    assert response.status_code == 201, response.text
    res_json = response.json
    assert res_json["name"] == payload["name"]
    assert res_json["slug"] == payload["slug"]
    assert res_json["description"] == payload["description"]
    assert res_json["created_by"] == "user"
    datetime.fromisoformat(res_json["creation_date"])

    _, response = await sanic_client.get("/api/data/groups", headers=user_headers)
    res_json = response.json
    assert response.status_code == 200
    assert len(res_json) == 1
    assert res_json[0]["name"] == payload["name"]

    payload = {
        "name": "New group",
        "slug": "group-1",
        "description": "Try to reuse a taken slug",
    }
    _, response = await sanic_client.post("/api/data/groups", headers=user_headers, json=payload)
    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_group_pagination(sanic_client, user_headers, admin_headers):
    for i in range(5):
        payload = {"name": f"group{i}", "slug": f"group{i}"}
        _, response = await sanic_client.post("/api/data/groups", headers=admin_headers, json=payload)
        assert response.status_code == 201
    for i in range(5, 15):
        payload = {"name": f"group{i}", "slug": f"group{i}"}
        _, response = await sanic_client.post("/api/data/groups", headers=user_headers, json=payload)
        assert response.status_code == 201
    _, res1 = await sanic_client.get("/api/data/groups", headers=user_headers, params={"per_page": 12, "page": 1})
    _, res2 = await sanic_client.get("/api/data/groups", headers=user_headers, params={"per_page": 12, "page": 2})
    assert res1.status_code == 200
    assert res2.status_code == 200
    res1_json = res1.json
    res2_json = res2.json
    assert len(res1_json) == 12
    assert len(res2_json) == 3
    assert res1_json[0]["name"] == "group0"
    assert res1_json[-1]["name"] == "group11"
    assert res2_json[0]["name"] == "group12"
    assert res2_json[-1]["name"] == "group14"
    _, res3 = await sanic_client.get("/api/data/groups", headers=admin_headers, params={"per_page": 20, "page": 1})
    res3_json = res3.json
    assert len(res3_json) == 15
    assert res3_json[0]["name"] == "group0"
    assert res3_json[-1]["name"] == "group14"


@pytest.mark.asyncio
async def test_group_patch_delete(sanic_client, user_headers):
    payload = {
        "name": "GroupOther",
        "slug": "group-other",
        "description": "Group Other Description",
    }
    _, response = await sanic_client.post("/api/data/groups", headers=user_headers, json=payload)
    assert response.status_code == 201, response.text
    payload = {
        "name": "Group1",
        "slug": "group-1",
        "description": "Group 1 Description",
    }
    _, response = await sanic_client.post("/api/data/groups", headers=user_headers, json=payload)
    assert response.status_code == 201, response.text
    res_json = response.json
    assert res_json["name"] == payload["name"]
    assert res_json["slug"] == payload["slug"]
    assert res_json["description"] == payload["description"]
    new_payload = {
        "name": "Group2",
        "slug": "group-2",
        "description": "Group 2 Description",
    }
    _, response = await sanic_client.patch("/api/data/groups/group-1", headers=user_headers, json=new_payload)
    assert response.status_code == 200, response.text
    res_json = response.json
    assert res_json["name"] == new_payload["name"]
    assert res_json["slug"] == new_payload["slug"]
    assert res_json["description"] == new_payload["description"]
    new_payload = {"slug": "group-other"}
    _, response = await sanic_client.patch("/api/data/groups/group-1", headers=user_headers, json=new_payload)
    assert response.status_code == 409  # The latest slug must be used to patch it is now group-2
    _, response = await sanic_client.delete("/api/data/groups/group-2", headers=user_headers)
    assert response.status_code == 204
    _, response = await sanic_client.get("/api/data/groups/group-2", headers=user_headers)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_group_members(sanic_client, user_headers):
    payload = {
        "name": "Group1",
        "slug": "group-1",
        "description": "Group 1 Description",
    }
    _, response = await sanic_client.post("/api/data/groups", headers=user_headers, json=payload)
    assert response.status_code == 201, response.text
    _, response = await sanic_client.get("/api/data/groups/group-1/members", headers=user_headers)
    assert response.status_code == 200, response.text
    res_json = response.json
    assert len(res_json) == 1
    assert res_json[0]["id"] == "user"
    assert res_json[0]["role"] == "owner"
    new_members = [{"id": "member-1", "role": "member"}]
    _, response = await sanic_client.patch("/api/data/groups/group-1/members", headers=user_headers, json=new_members)
    assert response.status_code == 200
    _, response = await sanic_client.get("/api/data/groups/group-1/members", headers=user_headers)
    assert response.status_code == 200, response.text
    res_json = response.json
    assert len(res_json) == 2
    find_member = list(filter(lambda x: x["id"] == "member-1", res_json))
    assert len(find_member) == 1
    assert find_member[0]["role"] == "member"


@pytest.mark.asyncio
async def test_removing_single_group_owner_not_allowed(sanic_client, user_headers):
    payload = {
        "name": "Group1",
        "slug": "group-1",
        "description": "Group 1 Description",
    }
    # Create a group
    _, response = await sanic_client.post("/api/data/groups", headers=user_headers, json=payload)
    assert response.status_code == 201, response.text
    _, response = await sanic_client.get("/api/data/groups/group-1/members", headers=user_headers)
    assert response.status_code == 200, response.text
    res_json = response.json
    assert len(res_json) == 1
    # Add a member
    new_members = [{"id": "member-1", "role": "member"}]
    _, response = await sanic_client.patch("/api/data/groups/group-1/members", headers=user_headers, json=new_members)
    assert response.status_code == 200
    _, response = await sanic_client.get("/api/data/groups/group-1/members", headers=user_headers)
    assert response.status_code == 200, response.text
    res_json = response.json
    assert len(res_json) == 2
    # Trying to remove the single owner from the group will fail
    _, response = await sanic_client.delete("/api/data/groups/group-1/members/user", headers=user_headers)
    assert response.status_code == 400
    # Make the other member owner
    new_members = [{"id": "member-1", "role": "owner"}]
    _, response = await sanic_client.patch("/api/data/groups/group-1/members", headers=user_headers, json=new_members)
    assert response.status_code == 200
    # Removing the original owner now works
    _, response = await sanic_client.delete("/api/data/groups/group-1/members/user", headers=user_headers)
    assert response.status_code == 204
    # Check that only one member remains
    _, response = await sanic_client.get("/api/data/groups/group-1/members", headers=user_headers)
    assert response.status_code == 200, response.text
    assert len(response.json) == 1
    assert response.json[0]["id"] == "member-1"
    assert response.json[0]["role"] == "owner"


@pytest.mark.asyncio
async def test_moving_project_across_groups(sanic_client, user_headers, regular_user: UserInfo):
    payload = {
        "name": "Group1",
        "slug": "group-1",
        "description": "Group 1 Description",
    }
    _, response = await sanic_client.post("/api/data/groups", headers=user_headers, json=payload)
    assert response.status_code == 201, response.text
    assert regular_user.email
    user_namespace = regular_user.email.split("@")[0]
    project_payload = {"name": "project-1", "slug": "project-1", "namespace": user_namespace}
    _, response = await sanic_client.post("/api/data/projects", headers=user_headers, json=project_payload)
    assert response.status_code == 201, response.text
    assert response.json["namespace"] == user_namespace
    project_id = response.json["id"]
    _, response = await sanic_client.get(f"/api/data/projects/{project_id}", headers=user_headers)
    assert response.status_code == 200, response.text
    assert response.json["namespace"] == user_namespace
    _, response = await sanic_client.patch(
        f"/api/data/projects/{project_id}", headers=user_headers, json={"namespace": "group-1"}
    )
    assert response.status_code == 200, response.text
    assert response.json["namespace"] == "group-1"
    _, response = await sanic_client.get(f"/api/data/projects/{project_id}", headers=user_headers)
    assert response.status_code == 200, response.text
    assert response.json["namespace"] == "group-1"


@pytest.mark.asyncio
async def test_removing_group_removes_projects(sanic_client, user_headers, regular_user: UserInfo):
    payload = {
        "name": "Group1",
        "slug": "group-1",
        "description": "Group 1 Description",
    }
    # Create a group
    _, response = await sanic_client.post("/api/data/groups", headers=user_headers, json=payload)
    assert response.status_code == 201, response.text
    assert regular_user.email
    # Create a project in the group
    project1_payload = {"name": "project-1", "slug": "project-1", "namespace": "group-1"}
    _, response = await sanic_client.post("/api/data/projects", headers=user_headers, json=project1_payload)
    assert response.status_code == 201, response.text
    project_id = response.json["id"]
    user_namespace = regular_user.email.split("@")[0]
    # Create a project in the user namespace
    project2_payload = {"name": "project-2", "slug": "project-2", "namespace": user_namespace}
    _, response = await sanic_client.post("/api/data/projects", headers=user_headers, json=project2_payload)
    assert response.status_code == 201, response.text
    # Ensure both projects show up when listing all projects
    _, response = await sanic_client.get("/api/data/projects", headers=user_headers)
    assert response.status_code == 200, response.text
    assert len(response.json) == 2
    # Delete the group that contains one project
    _, response = await sanic_client.delete("/api/data/groups/group-1", headers=user_headers)
    assert response.status_code == 204
    # The project in the group should be also deleted
    _, response = await sanic_client.get("/api/data/projects", headers=user_headers)
    assert response.status_code == 200, response.text
    assert len(response.json) == 1
    assert response.json[0]["namespace"] == user_namespace
    _, response = await sanic_client.get(f"/api/data/projects/{project_id}", headers=user_headers)
    assert response.status_code == 404
    # The group should not exist
    _, response = await sanic_client.get("/api/data/groups/group-1", headers=user_headers)
    assert response.status_code == 404