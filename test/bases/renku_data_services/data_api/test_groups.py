from datetime import datetime
from test.bases.renku_data_services.data_api.utils import merge_headers

import pytest

from renku_data_services.users.models import UserInfo


@pytest.mark.asyncio
async def test_group_creation_basic(sanic_client, user_headers) -> None:
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
async def test_group_pagination(sanic_client, user_headers, admin_headers) -> None:
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
async def test_group_patch_delete(sanic_client, user_headers) -> None:
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
async def test_group_members(sanic_client, user_headers) -> None:
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
    new_members = [{"id": "member-1", "role": "viewer"}]
    _, response = await sanic_client.patch("/api/data/groups/group-1/members", headers=user_headers, json=new_members)
    assert response.status_code == 200
    _, response = await sanic_client.get("/api/data/groups/group-1/members", headers=user_headers)
    assert response.status_code == 200, response.text
    res_json = response.json
    assert len(res_json) == 2
    find_member = list(filter(lambda x: x["id"] == "member-1", res_json))
    assert len(find_member) == 1
    assert find_member[0]["role"] == "viewer"


@pytest.mark.asyncio
async def test_removing_single_group_owner_not_allowed(sanic_client, user_headers, member_1_headers) -> None:
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
    new_members = [{"id": "member-1", "role": "editor"}]
    _, response = await sanic_client.patch("/api/data/groups/group-1/members", headers=user_headers, json=new_members)
    assert response.status_code == 200
    _, response = await sanic_client.get("/api/data/groups/group-1/members", headers=user_headers)
    assert response.status_code == 200, response.text
    res_json = response.json
    assert len(res_json) == 2
    # Trying to remove the single owner from the group will fail
    _, response = await sanic_client.delete("/api/data/groups/group-1/members/user", headers=user_headers)
    assert response.status_code == 401
    # Make the other member owner
    new_members = [{"id": "member-1", "role": "owner"}]
    _, response = await sanic_client.patch("/api/data/groups/group-1/members", headers=user_headers, json=new_members)
    assert response.status_code == 200
    # Removing the original owner now works
    _, response = await sanic_client.delete("/api/data/groups/group-1/members/user", headers=user_headers)
    assert response.status_code == 204
    # Check that only one member remains
    _, response = await sanic_client.get("/api/data/groups/group-1/members", headers=member_1_headers)
    assert response.status_code == 200, response.text
    assert len(response.json) == 1
    assert response.json[0]["id"] == "member-1"
    assert response.json[0]["role"] == "owner"


@pytest.mark.asyncio
async def test_moving_project_across_groups(sanic_client, user_headers, regular_user: UserInfo) -> None:
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
    headers = merge_headers(user_headers, {"If-Match": response.json["etag"]})
    _, response = await sanic_client.patch(
        f"/api/data/projects/{project_id}", headers=headers, json={"namespace": "group-1"}
    )
    assert response.status_code == 200, response.text
    assert response.json["namespace"] == "group-1"
    _, response = await sanic_client.get(f"/api/data/projects/{project_id}", headers=user_headers)
    assert response.status_code == 200, response.text
    assert response.json["namespace"] == "group-1"


@pytest.mark.asyncio
async def test_removing_group_removes_projects(sanic_client, user_headers, regular_user: UserInfo) -> None:
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
