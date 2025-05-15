from base64 import b64decode
from datetime import datetime

import pytest
from sanic_testing.testing import SanicASGITestClient

from renku_data_services.authz.models import Role, Visibility
from renku_data_services.data_api.dependencies import DependencyManager
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
from test.bases.renku_data_services.data_api.utils import merge_headers


@pytest.mark.asyncio
async def test_group_creation_basic(
    sanic_client: SanicASGITestClient, user_headers: dict[str, str], app_manager: DependencyManager
) -> None:
    await app_manager.search_updates_repo.clear_all()
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
    app_manager.metrics.group_created.assert_called_once()

    search_updates = await app_manager.search_updates_repo.select_next(20)
    assert len(search_updates) == 1
    assert search_updates[0].payload["id"] == group["id"]
    assert search_updates[0].payload["name"] == group["name"]
    assert search_updates[0].payload["description"] == group["description"]
    assert search_updates[0].payload["namespace"] == group["slug"]

    events = await app_manager.event_repo.get_pending_events()

    group_events = [e for e in events if e.get_message_type() == "group.added"]
    assert len(group_events) == 1
    group_event = deserialize_binary(b64decode(group_events[0].payload["payload"]), GroupAdded)
    assert group_event.id == group["id"]
    assert group_event.name == group["name"]
    assert group_event.description == group["description"]
    assert group_event.namespace == group["slug"]

    group_events = [e for e in events if e.get_message_type() == "memberGroup.added"]
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
async def test_group_pagination(
    sanic_client: SanicASGITestClient, user_headers: dict[str, str], admin_headers: dict[str, str]
) -> None:
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
    assert res1_json[0]["name"] == "group14"
    assert res1_json[-1]["name"] == "group3"
    assert res2_json[0]["name"] == "group2"
    assert res2_json[-1]["name"] == "group0"
    _, res3 = await sanic_client.get("/api/data/groups", headers=admin_headers, params={"per_page": 20, "page": 1})
    res3_json = res3.json
    assert len(res3_json) == 15
    assert res3_json[0]["name"] == "group14"
    assert res3_json[-1]["name"] == "group0"


@pytest.mark.asyncio
async def test_get_single_group(sanic_client, user_headers) -> None:
    payload = {
        "name": "Group1",
        "slug": "group-1",
        "description": "Group 1 Description",
    }
    _, response = await sanic_client.post("/api/data/groups", headers=user_headers, json=payload)
    assert response.status_code == 201, response.text
    _, response = await sanic_client.get("/api/data/groups/%3f", headers=user_headers)
    assert response.status_code == 404, response.text
    _, response = await sanic_client.get("/api/data/groups/group-1", headers=user_headers)
    assert response.status_code == 200, response.text
    group = response.json
    assert group["name"] == payload["name"]
    assert group["slug"] == payload["slug"]


@pytest.mark.asyncio
async def test_group_patch_delete(
    sanic_client: SanicASGITestClient, user_headers: dict[str, str], app_manager: DependencyManager
) -> None:
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
    await app_manager.search_updates_repo.clear_all()

    _, response = await sanic_client.patch("/api/data/groups/group-1", headers=user_headers, json=new_payload)
    assert response.status_code == 200, response.text
    group = response.json
    assert group["name"] == new_payload["name"]
    assert group["slug"] == new_payload["slug"]
    assert group["description"] == new_payload["description"]

    search_updates = await app_manager.search_updates_repo.select_next(20)
    assert len(search_updates) == 1
    assert search_updates[0].payload["namespace"] == group["slug"]
    for k in ["id", "name", "description"]:
        assert search_updates[0].payload[k] == group[k]

    events = await app_manager.event_repo.get_pending_events()

    group_events = [e for e in events if e.get_message_type() == "group.updated"]
    assert len(group_events) == 1
    group_event = deserialize_binary(b64decode(group_events[0].payload["payload"]), GroupUpdated)
    assert group_event.id == group["id"]
    assert group_event.name == group["name"]
    assert group_event.description == group["description"]
    assert group_event.namespace == group["slug"]

    await app_manager.search_updates_repo.clear_all()
    new_payload = {"slug": "group-other"}
    _, response = await sanic_client.patch("/api/data/groups/group-1", headers=user_headers, json=new_payload)
    assert response.status_code == 409  # The latest slug must be used to patch it is now group-2

    _, response = await sanic_client.delete("/api/data/groups/group-2", headers=user_headers)
    assert response.status_code == 204

    search_updates = await app_manager.search_updates_repo.select_next(20)
    assert len(search_updates) == 1
    assert search_updates[0].payload["id"] == group["id"]
    assert search_updates[0].payload["deleted"]

    events = await app_manager.event_repo.get_pending_events()

    group_events = [e for e in events if e.get_message_type() == "group.removed"]
    assert len(group_events) == 1
    group_event = deserialize_binary(b64decode(group_events[0].payload["payload"]), GroupRemoved)
    assert group_event.id == group["id"]

    _, response = await sanic_client.get("/api/data/groups/group-2", headers=user_headers)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_group_members(
    sanic_client: SanicASGITestClient, user_headers: dict[str, str], app_manager: DependencyManager
) -> None:
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

    await app_manager.search_updates_repo.clear_all()

    new_members = [{"id": "member-1", "role": "viewer"}]
    _, response = await sanic_client.patch("/api/data/groups/group-1/members", headers=user_headers, json=new_members)
    assert response.status_code == 200
    app_manager.metrics.group_member_added.assert_called_once()
    _, response = await sanic_client.get("/api/data/groups/group-1/members", headers=user_headers)
    assert response.status_code == 200, response.text
    members = response.json
    assert len(members) == 2
    member_1 = next(filter(lambda x: x["id"] == "member-1", members), None)
    assert member_1 is not None
    assert member_1["role"] == "viewer"

    search_updates = await app_manager.search_updates_repo.select_next(20)
    assert len(search_updates) == 0

    events = await app_manager.event_repo.get_pending_events()

    group_events = sorted([e for e in events if e.get_message_type() == "memberGroup.added"], key=lambda e: e.id)
    assert len(group_events) == 2
    group_event = deserialize_binary(b64decode(group_events[1].payload["payload"]), GroupMemberAdded)
    assert group_event.userId == member_1["id"]
    assert group_event.groupId == group["id"]
    assert group_event.role.value == "VIEWER"


@pytest.mark.asyncio
async def test_removing_single_group_owner_not_allowed(
    sanic_client: SanicASGITestClient,
    user_headers: dict[str, str],
    member_1_headers: dict[str, str],
    app_manager: DependencyManager,
) -> None:
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

    await app_manager.search_updates_repo.clear_all()

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
    assert response.status_code == 422
    # Make the other member owner
    new_members = [{"id": "member-1", "role": "owner"}]
    _, response = await sanic_client.patch("/api/data/groups/group-1/members", headers=user_headers, json=new_members)
    assert response.status_code == 200

    events = await app_manager.event_repo.get_pending_events()

    group_events = [e for e in events if e.get_message_type() == "memberGroup.updated"]
    assert len(group_events) == 1
    group_event = deserialize_binary(b64decode(group_events[0].payload["payload"]), GroupMemberUpdated)
    assert group_event.userId == "member-1"
    assert group_event.groupId == group["id"]
    assert group_event.role.value == "OWNER"

    search_updates = await app_manager.search_updates_repo.select_next(20)
    assert len(search_updates) == 0

    # Removing the original owner now works
    _, response = await sanic_client.delete("/api/data/groups/group-1/members/user", headers=user_headers)
    assert response.status_code == 204

    events = await app_manager.event_repo.get_pending_events()

    group_events = [e for e in events if e.get_message_type() == "memberGroup.removed"]
    assert len(group_events) == 1
    group_event = deserialize_binary(b64decode(group_events[0].payload["payload"]), GroupMemberRemoved)
    assert group_event.userId == "user"
    assert group_event.groupId == group["id"]

    search_updates = await app_manager.search_updates_repo.select_next(20)
    assert len(search_updates) == 0

    # Check that only one member remains
    _, response = await sanic_client.get("/api/data/groups/group-1/members", headers=member_1_headers)
    assert response.status_code == 200, response.text
    assert len(response.json) == 1
    assert response.json[0]["id"] == "member-1"
    assert response.json[0]["role"] == "owner"


@pytest.mark.asyncio
async def test_delete_group_member_invalid(sanic_client: SanicASGITestClient, user_headers: dict[str, str]) -> None:
    payload = {
        "name": "demo group",
        "slug": "demo-group",
    }
    _, response = await sanic_client.post("/api/data/groups", headers=user_headers, json=payload)
    assert response.status_code == 201, response.text
    group = response.json
    group_slug = group["slug"]

    _, response = await sanic_client.delete(f"/api/data/groups/{group_slug}/members/%3A", headers=user_headers)

    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_cannot_change_role_for_last_group_owner(
    sanic_client: SanicASGITestClient,
    user_headers: dict[str, str],
    regular_user: UserInfo,
    app_manager: DependencyManager,
    member_1_headers: dict[str, str],
) -> None:
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

    assert response.status_code == 422

    # Can change the owner role if another owner is added during an update
    new_roles.append({"id": "member-1", "role": "owner"})
    _, response = await sanic_client.patch("/api/data/groups/group-1/members", headers=user_headers, json=new_roles)

    assert response.status_code == 200

    # Add another owner and then check that cannot remove both owners
    new_roles = [{"id": regular_user.id, "role": "owner"}]
    _, response = await sanic_client.patch("/api/data/groups/group-1/members", headers=member_1_headers, json=new_roles)
    assert response.status_code == 200

    new_roles = [{"id": regular_user.id, "role": "viewer"}, {"id": "member-1", "role": "viewer"}]
    _, response = await sanic_client.patch("/api/data/groups/group-1/members", headers=user_headers, json=new_roles)

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_moving_project_across_groups(
    sanic_client: SanicASGITestClient, user_headers: dict[str, str], regular_user: UserInfo
) -> None:
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
async def test_removing_group_removes_projects(
    sanic_client: SanicASGITestClient, user_headers: dict[str, str], regular_user: UserInfo
) -> None:
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


@pytest.mark.asyncio
async def test_group_members_get_project_access(
    sanic_client: SanicASGITestClient,
    user_headers: dict[str, str],
    regular_user: UserInfo,
    member_1_user: UserInfo,
    member_1_headers: dict[str, str],
) -> None:
    group_slug = "group-1"
    payload = {
        "name": "Group1",
        "slug": group_slug,
        "description": "Group 1 Description",
    }
    # Create a group
    _, response = await sanic_client.post("/api/data/groups", headers=member_1_headers, json=payload)
    assert response.status_code == 201, response.text
    assert regular_user.email
    # Create a project in the group
    project1_payload = {
        "name": "project-1",
        "slug": "project-1",
        "namespace": "group-1",
        "visibility": Visibility.PRIVATE.value,
    }
    _, response = await sanic_client.post("/api/data/projects", headers=member_1_headers, json=project1_payload)
    assert response.status_code == 201, response.text
    project_id = response.json["id"]
    # Other user cannot see the private project
    _, response = await sanic_client.get(f"/api/data/projects/{project_id}", headers=user_headers)
    assert response.status_code == 404
    # Add other user to group
    _, response = await sanic_client.patch(
        f"/api/data/groups/{group_slug}/members",
        json=[{"id": regular_user.id, "role": Role.VIEWER.value}],
        headers=member_1_headers,
    )
    assert response.status_code == 200
    # Now other user can see the private project in the group
    _, response = await sanic_client.get(f"/api/data/projects/{project_id}", headers=user_headers)
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_get_group_anonymously(sanic_client, user_headers) -> None:
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
    new_members = [{"id": "member-1", "role": "viewer"}]
    _, response = await sanic_client.patch("/api/data/groups/group-1/members", headers=user_headers, json=new_members)
    assert response.status_code == 200

    _, response = await sanic_client.get("/api/data/groups/group-1")
    assert response.status_code == 200, response.text
    group = response.json
    assert group["name"] == payload["name"]
    assert group["slug"] == payload["slug"]
    assert group["description"] == payload["description"]
    assert group["created_by"] == "user"

    _, response = await sanic_client.get("/api/data/groups/group-1/members")
    assert response.status_code == 200, response.text
    members = response.json
    assert len(members) == 2
    member_1 = members[0]
    assert member_1["id"] == "user"
    assert member_1["role"] == "owner"
    member_2 = members[1]
    assert member_2["id"] == "member-1"
    assert member_2["role"] == "viewer"


@pytest.mark.asyncio
async def test_get_groups_with_direct_membership(sanic_client, user_headers, member_1_headers, member_1_user) -> None:
    # Create a group
    namespace = "my-group"
    payload = {
        "name": "Group",
        "slug": namespace,
    }
    _, response = await sanic_client.post("/api/data/groups", headers=user_headers, json=payload)
    assert response.status_code == 201, response.text
    group_1 = response.json

    # Create another group
    namespace_2 = "my-second-group"
    payload = {
        "name": "Group 2",
        "slug": namespace_2,
    }
    _, response = await sanic_client.post("/api/data/groups", headers=user_headers, json=payload)
    assert response.status_code == 201, response.text
    group_2 = response.json

    # Add member_1 to Group 2
    roles = [{"id": member_1_user.id, "role": "editor"}]
    _, response = await sanic_client.patch(f"/api/data/groups/{namespace_2}/members", headers=user_headers, json=roles)
    assert response.status_code == 200, response.text

    # Get groups where member_1 has direct membership
    parameters = {"direct_member": True}
    _, response = await sanic_client.get("/api/data/groups", headers=member_1_headers, params=parameters)
    assert response.status_code == 200, response.text
    groups = response.json
    assert len(groups) == 1
    group_ids = {g["id"] for g in groups}
    assert group_ids == {group_2["id"]}

    # Check that both groups can be seen without the filter
    _, response = await sanic_client.get("/api/data/groups", headers=member_1_headers)
    groups = response.json
    assert len(groups) == 2
    group_ids = {g["id"] for g in groups}
    assert group_ids == {group_1["id"], group_2["id"]}


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["viewer", "editor", "owner"])
async def test_get_group_permissions(sanic_client, admin_headers, user_headers, regular_user, role) -> None:
    namespace = "my-group"
    payload = {
        "name": "Group",
        "slug": namespace,
    }
    _, response = await sanic_client.post("/api/data/groups", headers=admin_headers, json=payload)
    assert response.status_code == 201, response.text
    roles = [{"id": regular_user.id, "role": role}]
    _, response = await sanic_client.patch(f"/api/data/groups/{namespace}/members", headers=admin_headers, json=roles)
    assert response.status_code == 200, response.text

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

    _, response = await sanic_client.get(f"/api/data/groups/{namespace}/permissions", headers=user_headers)

    assert response.status_code == 200, response.text
    assert response.json is not None
    permissions = response.json
    assert permissions.get("write") == expected_permissions["write"]
    assert permissions.get("delete") == expected_permissions["delete"]
    assert permissions.get("change_membership") == expected_permissions["change_membership"]


@pytest.mark.asyncio
async def test_get_group_permissions_unauthorized(sanic_client, admin_headers, user_headers) -> None:
    namespace = "my-group"
    payload = {
        "name": "Group",
        "slug": namespace,
    }
    _, response = await sanic_client.post("/api/data/groups", headers=admin_headers, json=payload)
    assert response.status_code == 201, response.text

    _, response = await sanic_client.get(f"/api/data/groups/{namespace}/permissions", headers=user_headers)

    assert response.status_code == 200, response.text
    assert response.json is not None
    permissions = response.json
    assert permissions.get("write") is False
    assert permissions.get("delete") is False
    assert permissions.get("change_membership") is False
