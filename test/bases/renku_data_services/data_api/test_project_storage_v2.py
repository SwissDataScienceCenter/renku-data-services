import pytest
from sanic_testing.testing import SanicASGITestClient

from renku_data_services.users.models import UserInfo


@pytest.mark.asyncio
async def test_post_project_storage(
    sanic_client: SanicASGITestClient,
    admin_headers: dict[str, str],
    user_headers: dict[str, str],
    regular_user: UserInfo,
    create_project,
    create_resource_pool,
    create_storage_flavor,
    create_storage_quota,
) -> None:
    project = await create_project(sanic_client, name="Test Project")
    project_id = project["id"]

    rp = await create_resource_pool(admin=True, public=False)
    rp_id = rp["id"]
    _, res = await sanic_client.post(
        f"/api/data/resource_pools/{rp_id}/members",
        headers=admin_headers,
        json=[{"member_type": "user", "id": regular_user.id, "role": "viewer"}],
    )

    sq = await create_storage_quota(resource_pool_id=rp_id)
    sq_id = sq["id"]

    payload = {"project_id": project_id, "storage_quota_id": sq_id, "requested_size": 16, "mount_path": "store"}

    _, res = await sanic_client.post("/api/data/storages", headers=admin_headers, json=payload)

    assert res.status_code == 201, res.text
    assert res.json is not None
    result = res.json
    assert isinstance(result.get("id"), str) and result.get("id") != ""
    assert result.get("project_id") == project_id
    assert result.get("storage_quota_id") == sq_id
    assert result.get("requested_size") == 16
    assert result.get("actual_size") is None
    assert result.get("mount_path") == "store"
    assert result.get("k8s_pvc_name") is None
    assert result.get("k8s_pvc_status") is None
    assert isinstance(result.get("creation_date"), str) and result.get("creation_date") != ""
    assert isinstance(result.get("updated_at"), str) and result.get("updated_at") != ""


@pytest.mark.asyncio
async def test_get_all_project_storages_as_admin(
    sanic_client: SanicASGITestClient, admin_headers: dict[str, str], create_project, create_project_storage
) -> None:
    project_1 = await create_project(sanic_client, name="Test Project 1")
    ps_1 = await create_project_storage(project_id=project_1["id"])
    project_2 = await create_project(sanic_client, name="Test Project 2")
    ps_2 = await create_project_storage(project_id=project_2["id"])

    _, res = await sanic_client.get("/api/data/storages", headers=admin_headers)

    assert res.status_code == 200, res.text
    assert res.json is not None
    assert isinstance(res.json, list)
    result = res.json
    assert len(result) == 2
    assert result == [ps_1, ps_2]
