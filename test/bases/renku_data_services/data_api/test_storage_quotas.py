import pytest
from sanic_testing.testing import SanicASGITestClient

from renku_data_services.users.models import UserInfo
from test.bases.renku_data_services.data_api.utils import merge_headers


@pytest.mark.asyncio
async def test_post_storage_quota(
    sanic_client: SanicASGITestClient,
    admin_headers: dict[str, str],
    create_resource_pool,
    create_storage_flavor,
) -> None:
    rp = await create_resource_pool(admin=True, public=False)
    rp_id = rp["id"]

    sf = await create_storage_flavor()
    sf_id = sf["id"]

    payload = {
        "resource_pool_id": rp_id,
        "storage_flavor_id": sf_id,
        "total_size": 64,
        "max_size": 16,
    }

    _, res = await sanic_client.post("/api/data/storage_quotas", headers=admin_headers, json=payload)

    assert res.status_code == 201, res.text
    assert res.json is not None
    result = res.json
    assert isinstance(result.get("id"), str) and result.get("id") != ""
    assert result.get("resource_pool_id") == rp_id
    assert result.get("storage_flavor_id") == sf_id
    assert result.get("storage_flavor_display_name") == sf["display_name"]
    assert result.get("storage_flavor_min_size") == sf["min_size"]
    assert result.get("storage_flavor_documentation") == sf["documentation"]
    assert result.get("total_size") == 64
    assert result.get("max_size") == 16
    assert isinstance(result.get("creation_date"), str) and result.get("creation_date") != ""
    assert isinstance(result.get("updated_at"), str) and result.get("updated_at") != ""


@pytest.mark.asyncio
async def test_get_all_storage_quotas_as_admin(
    sanic_client: SanicASGITestClient, admin_headers: dict[str, str], create_storage_quota
) -> None:
    sq_1 = await create_storage_quota()
    sq_2 = await create_storage_quota()

    _, res = await sanic_client.get("/api/data/storage_quotas", headers=admin_headers)

    assert res.status_code == 200, res.text
    assert res.json is not None
    assert isinstance(res.json, list)
    result = res.json
    assert len(result) == 2
    assert result == [sq_1, sq_2]


@pytest.mark.asyncio
async def test_get_all_storage_quotas_visible(
    sanic_client: SanicASGITestClient,
    admin_headers: dict[str, str],
    user_headers: dict[str, str],
    regular_user: UserInfo,
    create_resource_pool,
    create_storage_quota,
) -> None:
    rp_a = await create_resource_pool(admin=True, public=False)
    rp_a_id = rp_a["id"]
    rp_b = await create_resource_pool(admin=True, public=False)
    rp_b_id = rp_b["id"]

    _, res = await sanic_client.post(
        f"/api/data/resource_pools/{rp_a_id}/members",
        headers=admin_headers,
        json=[{"member_type": "user", "id": regular_user.id, "role": "viewer"}],
    )

    sq_1 = await create_storage_quota(resource_pool_id=rp_a_id)  # visible
    _sq_2 = await create_storage_quota(resource_pool_id=rp_b_id)  # not visible
    sq_3 = await create_storage_quota(resource_pool_id=rp_a_id)  # visible

    _, res = await sanic_client.get("/api/data/storage_quotas", headers=user_headers)

    assert res.status_code == 200, res.text
    assert res.json is not None
    assert isinstance(res.json, list)
    result = res.json
    assert len(result) == 2
    assert result == [sq_1, sq_3]


@pytest.mark.asyncio
async def test_get_storage_quota(
    sanic_client: SanicASGITestClient,
    admin_headers: dict[str, str],
    user_headers: dict[str, str],
    regular_user: UserInfo,
    create_resource_pool,
    create_storage_flavor,
    create_storage_quota,
) -> None:
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

    _, res = await sanic_client.get(f"/api/data/storage_quotas/{sq_id}", headers=user_headers)

    assert res.status_code == 200, res.text
    assert res.json is not None
    result = res.json
    assert isinstance(result.get("id"), str) and result.get("id") != ""
    assert result.get("resource_pool_id") == rp_id
    assert result.get("storage_flavor_id") == sf_id
    assert result.get("storage_flavor_display_name") == sf["display_name"]
    assert result.get("storage_flavor_min_size") == sf["min_size"]
    assert result.get("storage_flavor_documentation") == sf["documentation"]
    assert result.get("total_size") == 64
    assert result.get("max_size") == 16
    assert isinstance(result.get("creation_date"), str) and result.get("creation_date") != ""
    assert isinstance(result.get("updated_at"), str) and result.get("updated_at") != ""


@pytest.mark.asyncio
async def test_get_storage_quota_not_modified(
    sanic_client: SanicASGITestClient,
    admin_headers: dict[str, str],
    user_headers: dict[str, str],
    regular_user: UserInfo,
    create_resource_pool,
    create_storage_quota,
) -> None:
    rp = await create_resource_pool(admin=True, public=False)
    rp_id = rp["id"]
    _, res = await sanic_client.post(
        f"/api/data/resource_pools/{rp_id}/members",
        headers=admin_headers,
        json=[{"member_type": "user", "id": regular_user.id, "role": "viewer"}],
    )

    sq = await create_storage_quota(resource_pool_id=rp_id)
    sq_id = sq["id"]
    etag = sq["etag"]

    headers = merge_headers(user_headers, {"If-None-Match": etag})
    _, res = await sanic_client.get(f"/api/data/storage_quotas/{sq_id}", headers=headers)

    assert res.status_code == 304, res.text


@pytest.mark.asyncio
async def test_get_storage_quota_etag_depends_on_storage_flavor(
    sanic_client: SanicASGITestClient,
    admin_headers: dict[str, str],
    user_headers: dict[str, str],
    regular_user: UserInfo,
    create_resource_pool,
    create_storage_flavor,
    create_storage_quota,
) -> None:
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
    old_etag = sq["etag"]

    headers = merge_headers(admin_headers, {"If-Match": sf["etag"]})
    payload = {"display_name": "A new name"}
    _, res = await sanic_client.patch(f"/api/data/storage_flavors/{sf_id}", headers=headers, json=payload)

    _, res = await sanic_client.get(f"/api/data/storage_quotas/{sq_id}", headers=user_headers)

    assert res.status_code == 200, res.text
    result = res.json
    assert result.get("etag") != old_etag


# @pytest.mark.asyncio
# async def test_get_storage_flavor_not_modified(
#     sanic_client: SanicASGITestClient, admin_headers: dict[str, str], insert_storage_flavor
# ) -> None:
#     sf = await insert_storage_flavor()
#     sf_id = sf["id"]
#     etag = sf["etag"]

#     headers = {"If-None-Match": etag}
#     headers.update(admin_headers.copy())
#     _, res = await sanic_client.get(f"/api/data/storage_flavors/{sf_id}", headers=headers)

#     assert res.status_code == 304, res.text


# @pytest.mark.asyncio
# async def test_patch_storage_flavor(
#     sanic_client: SanicASGITestClient, admin_headers: dict[str, str], insert_storage_flavor
# ) -> None:
#     sf = await insert_storage_flavor()
#     sf_id = sf["id"]
#     etag = sf["etag"]

#     headers = {"If-Match": etag}
#     headers.update(admin_headers.copy())
#     payload = {"display_name": "A new name"}
#     _, res = await sanic_client.patch(f"/api/data/storage_flavors/{sf_id}", headers=headers, json=payload)

#     assert res.status_code == 200, res.text
#     assert res.json is not None
#     result = res.json
#     assert result.get("k8s_storage_class_name") == "some-storage-class"
#     assert result.get("display_name") == "A new name"


# @pytest.mark.asyncio
# async def test_patch_storage_flavor_conflict(
#     sanic_client: SanicASGITestClient, admin_headers: dict[str, str], insert_storage_flavor
# ) -> None:
#     sf = await insert_storage_flavor()
#     sf_id = sf["id"]

#     headers = {"If-Match": "invalid-etag"}
#     headers.update(admin_headers.copy())
#     payload = {"display_name": "A new name"}
#     _, res = await sanic_client.patch(f"/api/data/storage_flavors/{sf_id}", headers=headers, json=payload)

#     assert res.status_code == 409, res.text
#     assert res.json.get("error", {}).get("message") == f"Current ETag is {sf['etag']}, not invalid-etag."


# @pytest.mark.asyncio
# async def test_delete_storage_flavor(
#     sanic_client: SanicASGITestClient, admin_headers: dict[str, str], insert_storage_flavor
# ) -> None:
#     sf = await insert_storage_flavor()
#     sf_id = sf["id"]

#     _, res = await sanic_client.delete(f"/api/data/storage_flavors/{sf_id}", headers=admin_headers)

#     assert res.status_code == 204, res.text

#     _, res = await sanic_client.get(f"/api/data/storage_flavors/{sf_id}", headers=admin_headers)

#     assert res.status_code == 404, res.text


# @pytest.mark.asyncio
# async def test_delete_storage_flavor_non_existent(
#     sanic_client: SanicASGITestClient, admin_headers: dict[str, str]
# ) -> None:
#     sf_id = str(ULID())

#     _, res = await sanic_client.delete(f"/api/data/storage_flavors/{sf_id}", headers=admin_headers)

#     assert res.status_code == 204, res.text
