"""API tests for resource flavours and the classes linked to them."""

from typing import Any

import pytest
from sanic_testing.testing import SanicASGITestClient

from test.bases.renku_data_services.data_api.utils import create_rp
from test.utils import KindCluster

_FLAVOUR = {
    "name": "shared-small",
    "description": "Fits a standard node with room for the daemonset",
    "cpu": 2.0,
    "memory": 8,
    "gpu": 0,
    "max_storage": 200,
    "default_storage": 20,
}


async def _create_flavour(
    sanic_client: SanicASGITestClient, admin_headers: dict[str, str], **overrides: Any
) -> dict[str, Any]:
    payload = {**_FLAVOUR, **overrides}
    _, res = await sanic_client.post("/api/data/resource_flavours", headers=admin_headers, json=payload)
    assert res.status_code == 201, res.text
    return res.json


async def _create_pool(
    sanic_client: SanicASGITestClient, valid_resource_pool_payload: dict[str, Any]
) -> dict[str, Any]:
    _, res = await create_rp(valid_resource_pool_payload, sanic_client)
    assert res.status_code == 201, res.text
    return res.json


@pytest.mark.asyncio
async def test_flavour_crud(sanic_client: SanicASGITestClient, admin_headers: dict[str, str]) -> None:
    flavour = await _create_flavour(sanic_client, admin_headers)
    assert flavour["cpu"] == 2.0
    assert flavour["description"] == _FLAVOUR["description"]

    _, res = await sanic_client.get(f"/api/data/resource_flavours/{flavour['id']}", headers=admin_headers)
    assert res.status_code == 200, res.text
    assert res.json["name"] == "shared-small"

    _, res = await sanic_client.patch(
        f"/api/data/resource_flavours/{flavour['id']}", headers=admin_headers, json={"cpu": 4.0}
    )
    assert res.status_code == 200, res.text
    assert res.json["cpu"] == 4.0
    assert res.json["memory"] == 8

    _, res = await sanic_client.get("/api/data/resource_flavours", headers=admin_headers)
    assert res.status_code == 200, res.text
    assert [f["id"] for f in res.json] == [flavour["id"]]

    _, res = await sanic_client.delete(f"/api/data/resource_flavours/{flavour['id']}", headers=admin_headers)
    assert res.status_code == 204, res.text


@pytest.mark.asyncio
async def test_flavour_name_is_unique(sanic_client: SanicASGITestClient, admin_headers: dict[str, str]) -> None:
    await _create_flavour(sanic_client, admin_headers)
    _, res = await sanic_client.post("/api/data/resource_flavours", headers=admin_headers, json=_FLAVOUR)
    assert res.status_code == 409, res.text


@pytest.mark.asyncio
async def test_class_created_from_a_link_only(
    sanic_client: SanicASGITestClient,
    admin_headers: dict[str, str],
    valid_resource_pool_payload: dict[str, Any],
    cluster: KindCluster,
) -> None:
    flavour = await _create_flavour(sanic_client, admin_headers)
    pool = await _create_pool(sanic_client, valid_resource_pool_payload)

    _, res = await sanic_client.post(
        f"/api/data/resource_pools/{pool['id']}/classes",
        headers=admin_headers,
        json={"name": "linked-class", "default": False, "resource_flavour_id": flavour["id"]},
    )
    assert res.status_code == 201, res.text
    cls = res.json
    assert cls["name"] == "linked-class", "the class keeps its own name"
    assert cls["cpu"] == 2.0
    assert cls["memory"] == 8
    assert cls["max_storage"] == 200
    assert cls["default_storage"] == 20
    assert cls["resource_flavour_id"] == flavour["id"]


@pytest.mark.asyncio
async def test_pool_created_with_a_linked_class(
    sanic_client: SanicASGITestClient,
    admin_headers: dict[str, str],
    valid_resource_pool_payload: dict[str, Any],
    cluster: KindCluster,
) -> None:
    """A class may link to a flavour on the request that creates its pool, not only afterwards."""
    flavour = await _create_flavour(sanic_client, admin_headers)
    payload = {
        **valid_resource_pool_payload,
        "classes": [
            {
                "name": "plain-class",
                "default": True,
                "cpu": 1.0,
                "memory": 10,
                "gpu": 0,
                "max_storage": 100,
                "default_storage": 1,
            },
            {"name": "linked-class", "default": False, "resource_flavour_id": flavour["id"]},
        ],
    }
    pool = await _create_pool(sanic_client, payload)

    linked, plain = sorted(pool["classes"], key=lambda c: c["name"])
    assert plain["cpu"] == 1.0
    assert "resource_flavour_id" not in plain
    assert linked["name"] == "linked-class", "the class keeps its own name"
    assert linked["cpu"] == 2.0
    assert linked["memory"] == 8
    assert linked["max_storage"] == 200
    assert linked["default_storage"] == 20
    assert linked["resource_flavour_id"] == flavour["id"]

    _, res = await sanic_client.get(
        f"/api/data/resource_pools/{pool['id']}/classes/{linked['id']}", headers=admin_headers
    )
    assert res.status_code == 200, res.text
    assert res.json["cpu"] == 2.0


@pytest.mark.asyncio
async def test_pool_creation_rejects_an_unknown_flavour(
    sanic_client: SanicASGITestClient,
    valid_resource_pool_payload: dict[str, Any],
    cluster: KindCluster,
) -> None:
    payload = {
        **valid_resource_pool_payload,
        "classes": [
            {"name": "linked-class", "default": True, "resource_flavour_id": "01ARZ3NDEKTSV4RRFFQ69G5FAV"},
        ],
    }
    _, res = await create_rp(payload, sanic_client)
    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_class_rejects_shape_beside_a_link(
    sanic_client: SanicASGITestClient,
    admin_headers: dict[str, str],
    valid_resource_pool_payload: dict[str, Any],
    cluster: KindCluster,
) -> None:
    flavour = await _create_flavour(sanic_client, admin_headers)
    pool = await _create_pool(sanic_client, valid_resource_pool_payload)

    _, res = await sanic_client.post(
        f"/api/data/resource_pools/{pool['id']}/classes",
        headers=admin_headers,
        json={"name": "linked-class", "default": False, "cpu": 16.0, "resource_flavour_id": flavour["id"]},
    )
    assert res.status_code == 422, res.text


@pytest.mark.asyncio
async def test_class_without_a_link_still_needs_its_shape(
    sanic_client: SanicASGITestClient,
    admin_headers: dict[str, str],
    valid_resource_pool_payload: dict[str, Any],
    cluster: KindCluster,
) -> None:
    pool = await _create_pool(sanic_client, valid_resource_pool_payload)
    _, res = await sanic_client.post(
        f"/api/data/resource_pools/{pool['id']}/classes",
        headers=admin_headers,
        json={"name": "partial-class", "default": False, "cpu": 4.0},
    )
    assert res.status_code == 422, res.text


@pytest.mark.asyncio
async def test_a_flavour_edit_propagates_to_every_linked_class(
    sanic_client: SanicASGITestClient,
    admin_headers: dict[str, str],
    valid_resource_pool_payload: dict[str, Any],
    cluster: KindCluster,
) -> None:
    flavour = await _create_flavour(sanic_client, admin_headers)
    pool_a = await _create_pool(sanic_client, valid_resource_pool_payload)
    pool_b = await _create_pool(sanic_client, {**valid_resource_pool_payload, "name": "second-pool"})

    class_ids = []
    for pool in (pool_a, pool_b):
        _, res = await sanic_client.post(
            f"/api/data/resource_pools/{pool['id']}/classes",
            headers=admin_headers,
            json={"name": "linked-class", "default": False, "resource_flavour_id": flavour["id"]},
        )
        assert res.status_code == 201, res.text
        class_ids.append((pool["id"], res.json["id"]))

    _, res = await sanic_client.patch(
        f"/api/data/resource_flavours/{flavour['id']}",
        headers=admin_headers,
        json={"cpu": 16.0, "memory": 64, "name": "shared-large"},
    )
    assert res.status_code == 200, res.text

    for pool_id, class_id in class_ids:
        _, res = await sanic_client.get(f"/api/data/resource_pools/{pool_id}/classes/{class_id}", headers=admin_headers)
        assert res.status_code == 200, res.text
        assert res.json["cpu"] == 16.0
        assert res.json["memory"] == 64
        assert res.json["name"] == "linked-class", "renaming a flavour does not rename its classes"


@pytest.mark.asyncio
async def test_renaming_a_flavour_leaves_the_class_name_alone(
    sanic_client: SanicASGITestClient,
    admin_headers: dict[str, str],
    valid_resource_pool_payload: dict[str, Any],
    cluster: KindCluster,
) -> None:
    """A class name is never a snapshot, so the name filter has nothing to go stale."""
    flavour = await _create_flavour(sanic_client, admin_headers)
    pool = await _create_pool(sanic_client, valid_resource_pool_payload)
    _, res = await sanic_client.post(
        f"/api/data/resource_pools/{pool['id']}/classes",
        headers=admin_headers,
        json={"name": "linked-class", "default": False, "resource_flavour_id": flavour["id"]},
    )
    assert res.status_code == 201, res.text
    class_id = res.json["id"]

    _, res = await sanic_client.patch(
        f"/api/data/resource_flavours/{flavour['id']}", headers=admin_headers, json={"name": "renamed-flavour"}
    )
    assert res.status_code == 200, res.text

    _, res = await sanic_client.get(
        f"/api/data/resource_pools/{pool['id']}/classes?name=linked-class", headers=admin_headers
    )
    assert res.status_code == 200, res.text
    assert [c["id"] for c in res.json] == [class_id]

    _, res = await sanic_client.get(
        f"/api/data/resource_pools/{pool['id']}/classes?name=renamed-flavour", headers=admin_headers
    )
    assert res.status_code == 200, res.text
    assert res.json == []


@pytest.mark.asyncio
async def test_unlink_keeps_the_current_values(
    sanic_client: SanicASGITestClient,
    admin_headers: dict[str, str],
    valid_resource_pool_payload: dict[str, Any],
    cluster: KindCluster,
) -> None:
    flavour = await _create_flavour(sanic_client, admin_headers)
    pool = await _create_pool(sanic_client, valid_resource_pool_payload)
    _, res = await sanic_client.post(
        f"/api/data/resource_pools/{pool['id']}/classes",
        headers=admin_headers,
        json={"name": "linked-class", "default": False, "resource_flavour_id": flavour["id"]},
    )
    assert res.status_code == 201, res.text
    class_id = res.json["id"]

    _, res = await sanic_client.patch(
        f"/api/data/resource_flavours/{flavour['id']}", headers=admin_headers, json={"cpu": 8.0}
    )
    assert res.status_code == 200, res.text

    _, res = await sanic_client.delete(
        f"/api/data/resource_pools/{pool['id']}/classes/{class_id}/resource_flavour", headers=admin_headers
    )
    assert res.status_code == 204, res.text

    _, res = await sanic_client.get(f"/api/data/resource_pools/{pool['id']}/classes/{class_id}", headers=admin_headers)
    assert res.status_code == 200, res.text
    assert res.json["cpu"] == 8.0
    # None fields are dropped from the response, so an absent key is the unlinked state.
    assert "resource_flavour_id" not in res.json

    _, res = await sanic_client.patch(
        f"/api/data/resource_flavours/{flavour['id']}", headers=admin_headers, json={"cpu": 1.0}
    )
    assert res.status_code == 200, res.text

    _, res = await sanic_client.get(f"/api/data/resource_pools/{pool['id']}/classes/{class_id}", headers=admin_headers)
    assert res.status_code == 200, res.text
    assert res.json["cpu"] == 8.0


@pytest.mark.asyncio
async def test_a_flavour_edit_cannot_break_the_quota_of_a_linked_pool(
    sanic_client: SanicASGITestClient,
    admin_headers: dict[str, str],
    valid_resource_pool_payload: dict[str, Any],
    cluster: KindCluster,
) -> None:
    flavour = await _create_flavour(sanic_client, admin_headers)
    pool = await _create_pool(
        sanic_client, {**valid_resource_pool_payload, "quota": {"cpu": 8, "memory": 32, "gpu": 0}}
    )
    _, res = await sanic_client.post(
        f"/api/data/resource_pools/{pool['id']}/classes",
        headers=admin_headers,
        json={"name": "linked-class", "default": False, "resource_flavour_id": flavour["id"]},
    )
    assert res.status_code == 201, res.text
    class_id = res.json["id"]

    _, res = await sanic_client.patch(
        f"/api/data/resource_flavours/{flavour['id']}", headers=admin_headers, json={"cpu": 16.0}
    )
    assert res.status_code == 409, res.text
    assert "linked-class" in res.text

    _, res = await sanic_client.get(f"/api/data/resource_flavours/{flavour['id']}", headers=admin_headers)
    assert res.status_code == 200, res.text
    assert res.json["cpu"] == 2.0, "the rejected patch is rolled back"

    _, res = await sanic_client.get(f"/api/data/resource_pools/{pool['id']}/classes/{class_id}", headers=admin_headers)
    assert res.status_code == 200, res.text
    assert res.json["cpu"] == 2.0

    _, res = await sanic_client.patch(
        f"/api/data/resource_flavours/{flavour['id']}", headers=admin_headers, json={"cpu": 8.0, "max_storage": 400}
    )
    assert res.status_code == 200, res.text
    assert res.json["cpu"] == 8.0


@pytest.mark.asyncio
async def test_a_linked_flavour_cannot_be_deleted(
    sanic_client: SanicASGITestClient,
    admin_headers: dict[str, str],
    valid_resource_pool_payload: dict[str, Any],
    cluster: KindCluster,
) -> None:
    flavour = await _create_flavour(sanic_client, admin_headers)
    pool = await _create_pool(sanic_client, valid_resource_pool_payload)
    _, res = await sanic_client.post(
        f"/api/data/resource_pools/{pool['id']}/classes",
        headers=admin_headers,
        json={"name": "linked-class", "default": False, "resource_flavour_id": flavour["id"]},
    )
    assert res.status_code == 201, res.text

    _, res = await sanic_client.delete(f"/api/data/resource_flavours/{flavour['id']}", headers=admin_headers)
    assert res.status_code == 409, res.text
    assert "shared-small" in res.text


@pytest.mark.asyncio
async def test_flavours_are_admin_only(
    sanic_client: SanicASGITestClient, admin_headers: dict[str, str], user_headers: dict[str, str]
) -> None:
    flavour = await _create_flavour(sanic_client, admin_headers)

    _, res = await sanic_client.get("/api/data/resource_flavours", headers=user_headers)
    assert res.status_code == 403, res.text

    _, res = await sanic_client.get(f"/api/data/resource_flavours/{flavour['id']}", headers=user_headers)
    assert res.status_code == 403, res.text

    _, res = await sanic_client.post("/api/data/resource_flavours", headers=user_headers, json=_FLAVOUR)
    assert res.status_code == 403, res.text
