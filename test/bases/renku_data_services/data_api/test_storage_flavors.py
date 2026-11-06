from collections.abc import Callable, Coroutine
from typing import Any

import pytest
from sanic_testing.testing import SanicASGITestClient
from ulid import ULID


def merge_headers(*headers: dict[str, str]) -> dict[str, str]:
    """Merge multiple headers."""
    all_headers = dict()
    for h in headers:
        all_headers.update(**h)
    return all_headers


@pytest.fixture
def insert_storage_flavor(
    sanic_client: SanicASGITestClient, admin_headers: dict[str, str]
) -> Callable[[str, str], Coroutine[Any, Any, dict[str, Any]]]:
    async def insert_storage_flavor_helper(**kwargs: dict[str, Any]) -> None:
        payload = {
            "k8s_storage_class_name": "some-storage-class",
            "display_name": "A storage class",
            "min_size": 8,
            "admin_documentation": "Admin docs.",
            "documentation": "User docs.",
        }
        payload.update(kwargs.copy())
        _, res = await sanic_client.post("/api/data/storage_flavors", headers=admin_headers, json=payload)
        assert res.status_code == 201, res.text
        return res.json

    return insert_storage_flavor_helper


@pytest.mark.asyncio
async def test_post_storage_flavor(sanic_client: SanicASGITestClient, admin_headers: dict[str, str]) -> None:
    payload = {
        "k8s_storage_class_name": "some-storage-class",
        "display_name": "A storage class",
        "min_size": 8,
        "admin_documentation": "Admin docs.",
        "documentation": "User docs.",
    }

    _, res = await sanic_client.post("/api/data/storage_flavors", headers=admin_headers, json=payload)

    assert res.status_code == 201, res.text
    assert res.json is not None
    result = res.json
    assert isinstance(result.get("id"), str) and result.get("id") != ""
    assert result.get("k8s_storage_class_name") == "some-storage-class"
    assert result.get("display_name") == "A storage class"
    assert result.get("min_size") == 8
    assert result.get("admin_documentation") == "Admin docs."
    assert result.get("documentation") == "User docs."
    assert isinstance(result.get("creation_date"), str) and result.get("creation_date") != ""
    assert isinstance(result.get("updated_at"), str) and result.get("updated_at") != ""


@pytest.mark.asyncio
async def test_get_all_storage_flavors(
    sanic_client: SanicASGITestClient, admin_headers: dict[str, str], insert_storage_flavor
) -> None:
    sf_1 = await insert_storage_flavor(k8s_storage_class_name="storage-class-1")
    sf_2 = await insert_storage_flavor(k8s_storage_class_name="storage-class-2")

    _, res = await sanic_client.get("/api/data/storage_flavors", headers=admin_headers)

    assert res.status_code == 200, res.text
    assert res.json is not None
    assert isinstance(res.json, list)
    result = res.json
    assert len(result) == 2
    assert result == [sf_1, sf_2]


@pytest.mark.asyncio
async def test_get_storage_flavor(
    sanic_client: SanicASGITestClient, admin_headers: dict[str, str], insert_storage_flavor
) -> None:
    sf = await insert_storage_flavor()
    sf_id = sf["id"]

    _, res = await sanic_client.get(f"/api/data/storage_flavors/{sf_id}", headers=admin_headers)

    assert res.status_code == 200, res.text
    assert res.json is not None
    result = res.json
    assert isinstance(result.get("id"), str) and result.get("id") != ""
    assert result.get("k8s_storage_class_name") == "some-storage-class"
    assert result.get("display_name") == "A storage class"
    assert result.get("min_size") == 8
    assert result.get("admin_documentation") == "Admin docs."
    assert result.get("documentation") == "User docs."
    assert isinstance(result.get("creation_date"), str) and result.get("creation_date") != ""
    assert isinstance(result.get("updated_at"), str) and result.get("updated_at") != ""


@pytest.mark.asyncio
async def test_get_storage_flavor_not_modified(
    sanic_client: SanicASGITestClient, admin_headers: dict[str, str], insert_storage_flavor
) -> None:
    sf = await insert_storage_flavor()
    sf_id = sf["id"]
    etag = sf["etag"]

    headers = {"If-None-Match": etag}
    headers.update(admin_headers.copy())
    _, res = await sanic_client.get(f"/api/data/storage_flavors/{sf_id}", headers=headers)

    assert res.status_code == 304, res.text


@pytest.mark.asyncio
async def test_patch_storage_flavor(
    sanic_client: SanicASGITestClient, admin_headers: dict[str, str], insert_storage_flavor
) -> None:
    sf = await insert_storage_flavor()
    sf_id = sf["id"]
    etag = sf["etag"]

    headers = {"If-Match": etag}
    headers.update(admin_headers.copy())
    payload = {"display_name": "A new name"}
    _, res = await sanic_client.patch(f"/api/data/storage_flavors/{sf_id}", headers=headers, json=payload)

    assert res.status_code == 200, res.text
    assert res.json is not None
    result = res.json
    assert result.get("k8s_storage_class_name") == "some-storage-class"
    assert result.get("display_name") == "A new name"


@pytest.mark.asyncio
async def test_patch_storage_flavor_conflict(
    sanic_client: SanicASGITestClient, admin_headers: dict[str, str], insert_storage_flavor
) -> None:
    sf = await insert_storage_flavor()
    sf_id = sf["id"]

    headers = {"If-Match": "invalid-etag"}
    headers.update(admin_headers.copy())
    payload = {"display_name": "A new name"}
    _, res = await sanic_client.patch(f"/api/data/storage_flavors/{sf_id}", headers=headers, json=payload)

    assert res.status_code == 409, res.text
    assert res.json.get("error", {}).get("message") == f"Current ETag is {sf['etag']}, not invalid-etag."


@pytest.mark.asyncio
async def test_delete_storage_flavor(
    sanic_client: SanicASGITestClient, admin_headers: dict[str, str], insert_storage_flavor
) -> None:
    sf = await insert_storage_flavor()
    sf_id = sf["id"]

    _, res = await sanic_client.delete(f"/api/data/storage_flavors/{sf_id}", headers=admin_headers)

    assert res.status_code == 204, res.text

    _, res = await sanic_client.get(f"/api/data/storage_flavors/{sf_id}", headers=admin_headers)

    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_delete_storage_flavor_non_existent(
    sanic_client: SanicASGITestClient, admin_headers: dict[str, str]
) -> None:
    sf_id = str(ULID())

    _, res = await sanic_client.delete(f"/api/data/storage_flavors/{sf_id}", headers=admin_headers)

    assert res.status_code == 204, res.text
