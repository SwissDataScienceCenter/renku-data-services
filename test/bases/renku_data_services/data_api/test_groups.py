from base64 import b64decode
from datetime import datetime
from test.bases.renku_data_services.data_api.utils import merge_headers

import pytest

from renku_data_services.message_queue.avro_models.io.renku.events.v2 import (
    GroupAdded,
    GroupMemberAdded,
    GroupMemberRemoved,
    GroupMemberUpdated,
    GroupRemoved,
    GroupUpdated,
)
from renku_data_services.message_queue.models import deserialize_binary
from renku_data_services.users.models import UserInfo


@pytest.mark.asyncio
async def test_group_creation_basic(sanic_client, user_headers, app_config):
    payload = {
        "name": "Group1",
        "slug": "group-1",
        "description": "Group 1 Description",
    }

    _, response = await sanic_client.post("/api/data/groups", headers=user_headers, json=payload)

    assert response.status_code == 201, response.text
    group = response.json
    assert group["name"] == payload["name"]
    assert group["slug"] == payload["slug"]
    assert group["description"] == payload["description"]
    assert group["created_by"] == "user"
    datetime.fromisoformat(group["creation_date"])

    events = await app_config.event_repo._get_pending_events()

    group_events = [e for e in events if e.queue == "group.added"]
    assert len(group_events) == 1
    group_event = deserialize_binary(b64decode(group_events[0].payload["payload"]), GroupAdded)
    assert group_event.id == group["id"]
    assert group_event.name == group["name"]
    assert group_event.description == group["description"]
    assert group_event.namespace == group["slug"]

    group_events = [e for e in events if e.queue == "memberGroup.added"]
    assert len(group_events) == 1
    group_event = deserialize_binary(b64decode(group_events[0].payload["payload"]), GroupMemberAdded)
    assert group_event.userId == "user"
    assert group_event.groupId == group["id"]
    assert group_event.role.value == "OWNER"

    _, response = await sanic_client.get("/api/data/groups", headers=user_headers)
    group = response.json
    assert response.status_code == 200
    assert len(group) == 1
    assert group[0]["name"] == payload["name"]

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
async def test_group_patch_delete(sanic_client, user_headers, app_config):
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
    group = response.json
    assert group["name"] == payload["name"]
    assert group["slug"] == payload["slug"]
    assert group["description"] == payload["description"]
    new_payload = {
        "name": "Group2",
        "slug": "group-2",
        "description": "Group 2 Description",
    }

    _, response = await sanic_client.patch("/api/data/groups/group-1", headers=user_headers, json=new_payload)
    assert response.status_code == 200, response.text
    group = response.json
    assert group["name"] == new_payload["name"]
    assert group["slug"] == new_payload["slug"]
    assert group["description"] == new_payload["description"]

    events = await app_config.event_repo._get_pending_events()

    group_events = [e for e in events if e.queue == "group.updated"]
    assert len(group_events) == 1
    group_event = deserialize_binary(b64decode(group_events[0].payload["payload"]), GroupUpdated)
    assert group_event.id == group["id"]
    assert group_event.name == group["name"]
    assert group_event.description == group["description"]
    assert group_event.namespace == group["slug"]

    new_payload = {"slug": "group-other"}
    _, response = await sanic_client.patch("/api/data/groups/group-1", headers=user_headers, json=new_payload)
    assert response.status_code == 409  # The latest slug must be used to patch it is now group-2

    _, response = await sanic_client.delete("/api/data/groups/group-2", headers=user_headers)
    assert response.status_code == 204

    events = await app_config.event_repo._get_pending_events()

    group_events = [e for e in events if e.queue == "group.removed"]
    assert len(group_events) == 1
    group_event = deserialize_binary(b64decode(group_events[0].payload["payload"]), GroupRemoved)
    assert group_event.id == group["id"]

    _, response = await sanic_client.get("/api/data/groups/group-2", headers=user_headers)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_group_members(sanic_client, user_headers, app_config):
    payload = {
        "name": "Group1",
        "slug": "group-1",
        "description": "Group 1 Description",
    }
    _, response = await sanic_client.post("/api/data/groups", headers=user_headers, json=payload)
    assert response.status_code == 201, response.text
    group = response.json
    _, response = await sanic_client.get("/api/data/groups/group-1/members", headers=user_headers)
    assert response.status_code == 200, response.text
    members = response.json
    assert len(members) == 1
    assert members[0]["id"] == "user"
    assert members[0]["role"] == "owner"
    new_members = [{"id": "member-1", "role": "viewer"}]
    _, response = await sanic_client.patch("/api/data/groups/group-1/members", headers=user_headers, json=new_members)
    assert response.status_code == 200
    _, response = await sanic_client.get("/api/data/groups/group-1/members", headers=user_headers)
    assert response.status_code == 200, response.text
    members = response.json
    assert len(members) == 2
    member_1 = next(filter(lambda x: x["id"] == "member-1", members), None)
    assert member_1 is not None
    assert member_1["role"] == "viewer"

    events = await app_config.event_repo._get_pending_events()

    group_events = sorted([e for e in events if e.queue == "memberGroup.added"], key=lambda e: e.id)
    assert len(group_events) == 2
    group_event = deserialize_binary(b64decode(group_events[1].payload["payload"]), GroupMemberAdded)
    assert group_event.userId == member_1["id"]
    assert group_event.groupId == group["id"]
    assert group_event.role.value == "VIEWER"


@pytest.mark.asyncio
async def test_removing_single_group_owner_not_allowed(sanic_client, user_headers, member_1_headers, app_config):
    payload = {
        "name": "Group1",
        "slug": "group-1",
        "description": "Group 1 Description",
    }
    # Create a group
    _, response = await sanic_client.post("/api/data/groups", headers=user_headers, json=payload)
    assert response.status_code == 201, response.text
    group = response.json

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

    events = await app_config.event_repo._get_pending_events()

    group_events = [e for e in events if e.queue == "memberGroup.updated"]
    assert len(group_events) == 1
    group_event = deserialize_binary(b64decode(group_events[0].payload["payload"]), GroupMemberUpdated)
    assert group_event.userId == "member-1"
    assert group_event.groupId == group["id"]
    assert group_event.role.value == "OWNER"

    # Removing the original owner now works
    _, response = await sanic_client.delete("/api/data/groups/group-1/members/user", headers=user_headers)
    assert response.status_code == 204

    events = await app_config.event_repo._get_pending_events()

    group_events = [e for e in events if e.queue == "memberGroup.removed"]
    assert len(group_events) == 1
    group_event = deserialize_binary(b64decode(group_events[0].payload["payload"]), GroupMemberRemoved)
    assert group_event.userId == "user"
    assert group_event.groupId == group["id"]

    # Check that only one member remains
    _, response = await sanic_client.get("/api/data/groups/group-1/members", headers=member_1_headers)
    assert response.status_code == 200, response.text
    assert len(response.json) == 1
    assert response.json[0]["id"] == "member-1"
    assert response.json[0]["role"] == "owner"


@pytest.mark.asyncio
async def test_cannot_change_role_for_last_group_owner(sanic_client, user_headers, regular_user, app_config, member_1_headers):
    payload = {
        "name": "Group1",
        "slug": "group-1",
        "description": "Group 1 Description",
    }
    # Create a group
    _, response = await sanic_client.post("/api/data/groups", headers=user_headers, json=payload)
    assert response.status_code == 201, response.text

    # Cannot change the role of the sole group owner
    new_roles = [{"id": regular_user.id, "role": "viewer"}]
    _, response = await sanic_client.patch("/api/data/groups/group-1/members", headers=user_headers, json=new_roles)

    assert response.status_code == 401

    # Can change the owner role if another owner is added during an update
    new_roles.append({"id": "member-1", "role": "owner"})
    _, response = await sanic_client.patch("/api/data/groups/group-1/members", headers=user_headers, json=new_roles)

    assert response.status_code == 200


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
