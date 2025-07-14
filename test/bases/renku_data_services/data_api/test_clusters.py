from copy import deepcopy

import pytest
from sanic_testing.testing import SanicASGITestClient

cluster_payload = {
    "config_name": "a-filename_with.0.9_AND_UPPER_CASE.yaml",
    "name": "test-cluster-post",
    "session_protocol": "http",
    "session_host": "localhost",
    "session_port": 8080,
    "session_path": "/renku-sessions",
    "session_tls_secret_name": "a-server-domain-name-tls",
    "session_ingress_annotations": {
        "kubernetes.io/ingress.class": "nginx",
        "cert-manager.io/cluster-issuer": "letsencrypt-production",
        "nginx.ingress.kubernetes.io/configuration-snippet": """more_set_headers "Content-Security-Policy: """
        + """frame-ancestors 'self'""",
    },
}

cluster_payload_with_storage = deepcopy(cluster_payload)
cluster_payload_with_storage["session_storage_class"] = "an-arbitrary-class-name"


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
    "expected_status_code,auth,url,payload",
    [
        (401, False, "/api/data/clusters/", cluster_payload),
        (401, False, "/api/data/clusters/", cluster_payload_with_storage),
        (201, True, "/api/data/clusters/", cluster_payload),
        (201, True, "/api/data/clusters/", cluster_payload_with_storage),
    ],
)
@pytest.mark.asyncio
async def test_clusters_post(
    sanic_client: SanicASGITestClient,
    admin_headers: dict[str, str],
    expected_status_code: int,
    url: str,
    auth: bool,
    payload,
) -> None:
    if auth:
        _, res = await sanic_client.post(url, headers=admin_headers, json=payload)
    else:
        _, res = await sanic_client.post(url, json=payload)
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
        _, res = await sanic_client.post(base_url, headers=admin_headers, json=cluster_payload)
        assert res.status_code == 201, res.text
        cluster_id = res.json["id"]

    url = f"{base_url}/{cluster_id}"

    if auth:
        _, res = await sanic_client.get(url, headers=admin_headers)
    else:
        _, res = await sanic_client.get(url)
    assert res.status_code == expected_status_code, res.text


async def _clusters_request(
    sanic_client: SanicASGITestClient,
    method: str,
    admin_headers: dict[str, str],
    expected_status_code: int,
    auth: bool,
    cluster_id: str | None,
    payload: dict | None,
    post_payload: dict,
) -> None:
    base_url = "/api/data/clusters"

    check_payload = None
    if cluster_id is None:
        _, res = await sanic_client.post(base_url, headers=admin_headers, json=post_payload)
        assert res.status_code == 201, res.text
        cluster_id = res.json["id"]

        check_payload = deepcopy(payload)
        if "id" not in check_payload:
            check_payload["id"] = cluster_id

    url = f"{base_url}/{cluster_id}"

    if auth:
        _, res = await sanic_client.request(url=url, method=method, headers=admin_headers, json=payload)
    else:
        _, res = await sanic_client.request(url=url, method=method, json=payload)

    assert res.status_code == expected_status_code, res.text
    if res.is_success and check_payload is not None:
        assert res.json == check_payload, f"\nRESULT: {res.json}\nEXPECT: {check_payload}\n"


put_patch_common_test_inputs = [
    (401, False, "ZZZZZZZZZZZZZZZZZZZZZZZZZZ", None, cluster_payload),
    (422, True, "ZZZZZZZZZZZZZZZZZZZZZZZZZZ", None, cluster_payload),
    (401, False, "ZZZZZZZZZZZZZZZZZZZZZZZZZZYY", None, cluster_payload),
    (422, True, "ZZZZZZZZZZZZZZZZZZZZZZZZZZYY", None, cluster_payload),
    (401, False, "XX", None, cluster_payload),
    (422, True, "XX", None, cluster_payload),
    (401, False, None, {"name": "new_name"}, cluster_payload),
    (201, True, None, cluster_payload, cluster_payload),
    (201, True, None, cluster_payload_with_storage, cluster_payload_with_storage),
    (201, True, None, cluster_payload_with_storage, cluster_payload),
    (
        422,
        True,
        None,
        {"name": "new_name", "config_name": "a-filename.yaml", "unknown_field": 42},
        cluster_payload,
    ),
    (404, True, "ZZZZZZZZZZZZZZZZZZZZZZZZZZ", cluster_payload, cluster_payload),
]


@pytest.mark.parametrize(
    "expected_status_code,auth,cluster_id,payload,post_payload",
    put_patch_common_test_inputs
    + [
        (201, True, None, cluster_payload, cluster_payload_with_storage),
    ],
)
@pytest.mark.asyncio
async def test_clusters_put(
    sanic_client: SanicASGITestClient,
    admin_headers: dict[str, str],
    expected_status_code: int,
    auth: bool,
    cluster_id: str | None,
    payload: dict | None,
    post_payload: dict,
) -> None:
    await _clusters_request(
        sanic_client, "PUT", admin_headers, expected_status_code, auth, cluster_id, payload, post_payload
    )


@pytest.mark.parametrize("expected_status_code,auth,cluster_id,payload,post_payload", put_patch_common_test_inputs)
@pytest.mark.asyncio
async def test_clusters_patch(
    sanic_client: SanicASGITestClient,
    admin_headers: dict[str, str],
    expected_status_code: int,
    auth: bool,
    cluster_id: str | None,
    payload: dict | None,
    post_payload: dict,
) -> None:
    await _clusters_request(
        sanic_client, "PATCH", admin_headers, expected_status_code, auth, cluster_id, payload, post_payload
    )


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
        _, res = await sanic_client.post(base_url, headers=admin_headers, json=cluster_payload)
        assert res.status_code == 201, res.text
        cluster_id = res.json["id"]

    url = f"{base_url}/{cluster_id}"

    if auth:
        _, res = await sanic_client.delete(url, headers=admin_headers)
    else:
        _, res = await sanic_client.delete(url)
    assert res.status_code == expected_status_code, res.text
