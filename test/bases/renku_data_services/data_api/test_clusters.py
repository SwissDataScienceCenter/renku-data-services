from copy import deepcopy

import pytest
from sanic_testing.testing import SanicASGITestClient


@pytest.mark.parametrize(
    "expected_status_code,auth,url",
    [
        (401, False, "/api/data/clusters/"),
        (200, True, "/api/data/clusters/"),
    ],
)
@pytest.mark.asyncio
async def test_clusters_get(
    sanic_client: SanicASGITestClient, admin_headers: dict[str, str], expected_status_code: int, auth: bool, url: str
) -> None:
    if auth:
        _, res = await sanic_client.get(url, headers=admin_headers)
    else:
        _, res = await sanic_client.get(url)
    assert res.status_code == expected_status_code, res.text


@pytest.mark.parametrize(
    "expected_status_code,auth,url",
    [
        (401, False, "/api/data/clusters/"),
        (201, True, "/api/data/clusters/"),
    ],
)
@pytest.mark.asyncio
async def test_clusters_post(
    sanic_client: SanicASGITestClient, admin_headers: dict[str, str], expected_status_code: int, url: str, auth: bool
) -> None:
    if auth:
        _, res = await sanic_client.post(url, headers=admin_headers, json={"name": "test-cluster-post"})
    else:
        _, res = await sanic_client.post(url, json={"name": "test-cluster-post"})
    assert res.status_code == expected_status_code, res.text


@pytest.mark.parametrize(
    "expected_status_code,auth,cluster_id",
    [
        (401, False, "ZZZZZZZZZZZZZZZZZZZZZZZZZZ"),
        (404, True, "ZZZZZZZZZZZZZZZZZZZZZZZZZZ"),
        (401, False, "ZZZZZZZZZZZZZZZZZZZZZZZZZZYY"),
        (404, True, "ZZZZZZZZZZZZZZZZZZZZZZZZZZYY"),
        (401, False, "XX"),
        (404, True, "XX"),
        (401, False, None),
        (200, True, None),
    ],
)
@pytest.mark.asyncio
async def test_cluster_get_id(
    sanic_client: SanicASGITestClient,
    admin_headers: dict[str, str],
    expected_status_code: int,
    auth: bool,
    cluster_id: str | None,
) -> None:
    base_url = "/api/data/clusters"

    if cluster_id is None:
        _, res = await sanic_client.post(base_url, headers=admin_headers, json={"name": "test-cluster-get"})
        assert res.status_code == 201, res.text
        cluster_id = res.json["id"]

    url = f"{base_url}/{cluster_id}"

    if auth:
        _, res = await sanic_client.get(url, headers=admin_headers)
    else:
        _, res = await sanic_client.get(url)
    assert res.status_code == expected_status_code, res.text


async def _cluster_request(
    sanic_client: SanicASGITestClient,
    method: str,
    admin_headers: dict[str, str],
    expected_status_code: int,
    auth: bool,
    cluster_id: str | None,
    payload: dict | None,
) -> None:
    base_url = "/api/data/clusters"

    check_payload = None
    if cluster_id is None:
        _, res = await sanic_client.post(base_url, headers=admin_headers, json={"name": "test-cluster"})
        assert res.status_code == 201, res.text
        cluster_id = res.json["id"]

        check_payload = deepcopy(payload)
        if "id" not in check_payload.keys():
            check_payload["id"] = cluster_id

    url = f"{base_url}/{cluster_id}"

    if auth:
        _, res = await sanic_client.request(url=url, method=method, headers=admin_headers, json=payload)
    else:
        _, res = await sanic_client.request(url=url, method=method, json=payload)

    assert res.status_code == expected_status_code, res.text
    if res.is_success and check_payload is not None:
        assert res.json == check_payload, res.json


put_patch_common_test_inputs = [
    (401, False, "ZZZZZZZZZZZZZZZZZZZZZZZZZZ", None),
    (422, True, "ZZZZZZZZZZZZZZZZZZZZZZZZZZ", None),
    (401, False, "ZZZZZZZZZZZZZZZZZZZZZZZZZZYY", None),
    (422, True, "ZZZZZZZZZZZZZZZZZZZZZZZZZZYY", None),
    (401, False, "XX", None),
    (422, True, "XX", None),
    (401, False, None, {"name": "new_name"}),
    (201, True, None, {"name": "new_name"}),
    (422, True, None, {"name": "new_name", "unknown_field": 42}),
    (422, True, None, {"name": "new_name", "id": "ZZZZZZZZZZZZZZZZZZZZZZZZZZ"}),
]


@pytest.mark.parametrize("expected_status_code,auth,cluster_id,payload", put_patch_common_test_inputs + [
    (422, True, "ZZZZZZZZZZZZZZZZZZZZZZZZZZ", {"name": "test-cluster", "id": "0AD9NJBYME97DCQF9VZVA2M156"}),
    (422, True, None, {"name": "test-cluster", "id": "0AD9NJBYME97DCQF9VZVA2M156"}),
])
@pytest.mark.asyncio
async def test_cluster_put(
    sanic_client: SanicASGITestClient,
    admin_headers: dict[str, str],
    expected_status_code: int,
    auth: bool,
    cluster_id: str | None,
    payload: dict | None,
) -> None:
    await _cluster_request(sanic_client, "PUT", admin_headers, expected_status_code, auth, cluster_id, payload)


@pytest.mark.parametrize("expected_status_code,auth,cluster_id,payload", put_patch_common_test_inputs + [
    (404, True, "ZZZZZZZZZZZZZZZZZZZZZZZZZZ", {"name": "test-cluster", "id": "0AD9NJBYME97DCQF9VZVA2M156"}),
    (201, True, None, {"name": "test-cluster", "id": "0AD9NJBYME97DCQF9VZVA2M156"}),
])
@pytest.mark.asyncio
async def test_cluster_patch(
    sanic_client: SanicASGITestClient,
    admin_headers: dict[str, str],
    expected_status_code: int,
    auth: bool,
    cluster_id: str | None,
    payload: dict | None,
) -> None:
    await _cluster_request(sanic_client, "PATCH", admin_headers, expected_status_code, auth, cluster_id, payload)


@pytest.mark.parametrize(
    "expected_status_code,auth,cluster_id",
    [
        (401, False, "ZZZZZZZZZZZZZZZZZZZZZZZZZZ"),
        (204, True, "ZZZZZZZZZZZZZZZZZZZZZZZZZZ"),
        (401, False, "ZZZZZZZZZZZZZZZZZZZZZZZZZZYY"),
        (204, True, "ZZZZZZZZZZZZZZZZZZZZZZZZZZYY"),
        (401, False, "XX"),
        (204, True, "XX"),
        (401, False, None),
        (204, True, None),
    ],
)
@pytest.mark.asyncio
async def test_cluster_delete(
    sanic_client: SanicASGITestClient,
    admin_headers: dict[str, str],
    expected_status_code: int,
    auth: bool,
    cluster_id: str | None,
) -> None:
    base_url = "/api/data/clusters"

    if cluster_id is None:
        _, res = await sanic_client.post(base_url, headers=admin_headers, json={"name": "test-cluster-get"})
        assert res.status_code == 201, res.text
        cluster_id = res.json["id"]

    url = f"{base_url}/{cluster_id}"

    if auth:
        _, res = await sanic_client.delete(url, headers=admin_headers)
    else:
        _, res = await sanic_client.delete(url)
    assert res.status_code == expected_status_code, res.text
