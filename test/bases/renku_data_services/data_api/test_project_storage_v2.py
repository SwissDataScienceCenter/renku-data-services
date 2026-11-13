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

    sf = await create_storage_flavor()
    sf_id = sf["id"]

    sq = await create_storage_quota(resource_pool_id=rp_id, storage_flavor_id=sf_id)
    sq_id = sq["id"]

    payload = {"project_id": project_id, "storage_quota_id": sq_id, "requested_size": 16, "mount_path": "store"}

    _, res = await sanic_client.post("/api/data/project_storage_v2", headers=admin_headers, json=payload)

    assert res.status_code == 201, res.text
    # TODO
