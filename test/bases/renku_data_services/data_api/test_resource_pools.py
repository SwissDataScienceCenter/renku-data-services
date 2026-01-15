import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from sanic_testing.testing import SanicASGITestClient

from test.bases.renku_data_services.data_api.utils import create_rp
from test.utils import KindCluster

resource_pool_payload = [
    (
        {
            "name": "test-name",
            "classes": [
                {
                    "cpu": 1.0,
                    "memory": 10,
                    "gpu": 0,
                    "name": "test-class-name",
                    "max_storage": 100,
                    "default_storage": 1,
                    "default": True,
                    "node_affinities": [],
                    "tolerations": [],
                }
            ],
            "quota": {"cpu": 100, "memory": 100, "gpu": 0},
            "default": False,
            "public": True,
            "idle_threshold": 86400,
            "hibernation_threshold": 99999,
            "hibernation_warning_period": 888,
            "cluster_id": "change_me",
        },
        201,
    ),
    (
        {
            "name": "test-name",
            "classes": [
                {
                    "cpu": 1.0,
                    "memory": 10,
                    "gpu": 0,
                    "name": "test-class-name",
                    "max_storage": 100,
                    "default_storage": 1,
                    "default": True,
                }
            ],
            "quota": "something",
            "default": False,
            "public": True,
        },
        422,
    ),
]


@pytest.mark.parametrize(
    "payload,expected_status_code",
    resource_pool_payload,
)
@pytest.mark.asyncio
@pytest.mark.xdist_group("sessions")  # Needs to run on the same worker as the rest of the sessions tests
async def test_resource_pool_creation(
    sanic_client: SanicASGITestClient,
    payload: dict[str, Any],
    expected_status_code: int,
    cluster: KindCluster,
) -> None:
    payload = deepcopy(payload)
    if "cluster_id" in payload:
        payload["cluster_id"] = None

    _, res = await create_rp(payload, sanic_client)
    assert res.status_code == expected_status_code, res.text


@pytest.mark.parametrize(
    "payload,expected_status_code",
    resource_pool_payload,
)
@pytest.mark.asyncio
@pytest.mark.xdist_group("sessions")  # Needs to run on the same worker as the rest of the sessions tests
async def test_resource_pool_creation_with_cluster_ids(
    sanic_client: SanicASGITestClient,
    payload: dict[str, Any],
    expected_status_code: int,
    cluster: KindCluster,
    kubeconfig_path: Path,
    monkeypatch,
) -> None:
    payload = deepcopy(payload)
    monkeypatch.setenv("ALWAYS_READ_CLUSTERS", "true")
    if "cluster_id" in payload:
        _, res = await sanic_client.post(
            "/api/data/clusters",
            json={
                "name": "test-name",
                "config_name": kubeconfig_path.name,
                "session_protocol": "http",
                "session_host": "localhost",
                "session_port": 8080,
                "session_path": "/renku-sessions",
                "session_ingress_annotations": {},
                "session_tls_secret_name": "a-domain-name-tls",
            },
            headers={"Authorization": 'Bearer {"is_admin": true}'},
        )
        assert res.status_code == 201, res.text
        payload["cluster_id"] = res.json["id"]

    _, res = await create_rp(payload, sanic_client)
    assert res.status_code == expected_status_code, res.text

    if "cluster_id" in payload:
        assert "cluster" in res.json
        assert "id" in res.json["cluster"]
        assert res.json["cluster"]["id"] == payload["cluster_id"]


@pytest.mark.parametrize(
    "payload,expected_status_code",
    resource_pool_payload,
)
@pytest.mark.asyncio
@pytest.mark.xdist_group("sessions")  # Needs to run on the same worker as the rest of the sessions tests
async def test_resource_pool_creation_with_remote(
    sanic_client: SanicASGITestClient,
    admin_headers: dict[str, str],
    payload: dict[str, Any],
    expected_status_code: int,
    cluster: KindCluster,
) -> None:
    # Create a provider
    provider_payload = {
        "id": "some-provider",
        "kind": "gitlab",
        "client_id": "some-client-id",
        "display_name": "my oauth2 application",
        "scope": "api",
        "url": "https://example.org",
    }
    _, res = await sanic_client.post("/api/data/oauth2/providers", headers=admin_headers, json=provider_payload)
    assert res.status_code == 201, res.text

    payload = deepcopy(payload)
    if "cluster_id" in payload:
        payload["cluster_id"] = None
    payload["default"] = False
    payload["public"] = False
    payload["remote"] = {
        "kind": "firecrest",
        "provider_id": provider_payload["id"],
        "api_url": "https://example.org",
        "system_name": "my-system",
    }

    _, res = await create_rp(payload, sanic_client)
    assert res.status_code == expected_status_code, res.text

    if res.status_code >= 200 and res.status_code < 400:
        assert res.json is not None
        rp = res.json
        assert rp.get("remote") == {
            "kind": "firecrest",
            "provider_id": provider_payload["id"],
            "api_url": "https://example.org",
            "system_name": "my-system",
        }


@pytest.mark.parametrize(
    "payload,expected_status_code",
    resource_pool_payload,
)
@pytest.mark.asyncio
@pytest.mark.xdist_group("sessions")  # Needs to run on the same worker as the rest of the sessions tests
async def test_resource_pool_creation_with_platform(
    sanic_client: SanicASGITestClient,
    admin_headers: dict[str, str],
    payload: dict[str, Any],
    expected_status_code: int,
    cluster: KindCluster,
) -> None:
    payload = deepcopy(payload)
    if "cluster_id" in payload:
        payload["cluster_id"] = None
    payload["default"] = False
    payload["public"] = False
    payload["platform"] = "linux/arm64"

    _, res = await create_rp(payload, sanic_client)
    assert res.status_code == expected_status_code, res.text

    if res.status_code >= 200 and res.status_code < 400:
        assert res.json is not None
        rp = res.json
        assert rp.get("platform") == "linux/arm64"


@pytest.mark.asyncio
@pytest.mark.xdist_group("sessions")  # Needs to run on the same worker as the rest of the sessions tests
async def test_resource_pool_quotas(
    sanic_client: SanicASGITestClient,
    valid_resource_pool_payload: dict[str, Any],
    cluster: KindCluster,
) -> None:
    _, res = await create_rp(valid_resource_pool_payload, sanic_client)
    assert res.status_code == 201

    assert res.json.get("idle_threshold") == 86400
    assert res.json.get("hibernation_threshold") == 99999
    assert res.json.get("hibernation_warning_period") == 888


@pytest.mark.asyncio
@pytest.mark.xdist_group("sessions")  # Needs to run on the same worker as the rest of the sessions tests
async def test_resource_class_filtering(
    sanic_client: SanicASGITestClient,
    admin_headers: dict[str, str],
    valid_resource_pool_payload: dict[str, Any],
    cluster: KindCluster,
) -> None:
    new_classes = [
        {
            "name": "resource class 1",
            "cpu": 1.0,
            "memory": 2,
            "gpu": 0,
            "max_storage": 100,
            "default": True,
            "default_storage": 1,
            "node_affinities": [],
            "tolerations": [],
        },
        {
            "name": "resource class 2",
            "cpu": 2,
            "memory": 4,
            "gpu": 0,
            "max_storage": 100,
            "default": False,
            "default_storage": 4,
            "node_affinities": [],
            "tolerations": [],
        },
        {
            "name": "resource class 3",
            "cpu": 2.0,
            "memory": 32,
            "gpu": 1,
            "max_storage": 100,
            "default": False,
            "default_storage": 30,
            "node_affinities": [],
            "tolerations": [],
        },
    ]
    payload = valid_resource_pool_payload
    payload["quota"] = {"cpu": 100, "memory": 100, "gpu": 100}
    payload["classes"] = new_classes
    _, res = await create_rp(payload, sanic_client)
    assert res.status_code == 201
    _, res = await sanic_client.get(
        "/api/data/resource_pools",
        params={"cpu": 1, "gpu": 1},
        headers=admin_headers,
    )
    assert res.status_code == 200
    assert len(res.json) == 1
    rp_filtered = res.json[0]
    assert len(rp_filtered["classes"]) == len(new_classes)
    matching_classes = list(filter(lambda x: x["matching"], rp_filtered["classes"]))
    assert len(matching_classes) == 1
    matching_class = matching_classes[0]
    matching_class.pop("id")
    matching_class.pop("matching")
    assert matching_class == new_classes[2]
    # Test without any filtering
    _, res = await sanic_client.get(
        "/api/data/resource_pools",
        headers=admin_headers,
    )
    assert res.status_code == 200
    assert len(res.json) == 1
    assert len(res.json[0]["classes"]) == len(new_classes)


@pytest.mark.asyncio
@pytest.mark.xdist_group("sessions")  # Needs to run on the same worker as the rest of the sessions tests
async def test_resource_class_ordering(
    sanic_client: SanicASGITestClient,
    admin_headers: dict[str, str],
    valid_resource_pool_payload: dict[str, Any],
    cluster: KindCluster,
) -> None:
    new_classes = [
        {
            "name": "resource class 5",
            "cpu": 0.1,
            "memory": 1,
            "gpu": 1,
            "max_storage": 1,
            "default": False,
            "default_storage": 1,
            "node_affinities": [],
            "tolerations": [],
        },
        {
            "name": "resource class 4",
            "cpu": 9.0,
            "memory": 1,
            "gpu": 0,
            "max_storage": 1,
            "default": False,
            "default_storage": 1,
            "node_affinities": [],
            "tolerations": [],
        },
        {
            "name": "resource class 3",
            "cpu": 0.1,
            "memory": 100,
            "gpu": 0,
            "max_storage": 1,
            "default": False,
            "default_storage": 1,
            "node_affinities": [],
            "tolerations": [],
        },
        {
            "name": "resource class 2",
            "cpu": 0.1,
            "memory": 1,
            "gpu": 0,
            "max_storage": 100,
            "default": False,
            "default_storage": 1,
            "node_affinities": [],
            "tolerations": [],
        },
        {
            "name": "resource class 1",
            "cpu": 0.1,
            "memory": 1,
            "gpu": 0,
            "max_storage": 10,
            "default": True,
            "default_storage": 1,
            "node_affinities": [],
            "tolerations": [],
        },
    ]
    payload = valid_resource_pool_payload
    payload["quota"] = {"cpu": 100, "memory": 100, "gpu": 100}
    payload["classes"] = new_classes
    _, res = await create_rp(payload, sanic_client)
    assert res.status_code == 201
    _, res = await sanic_client.get(
        "/api/data/resource_pools",
        params={"cpu": 1, "gpu": 1},
        headers=admin_headers,
    )
    assert res.status_code == 200
    assert len(res.json) == 1
    rp_filtered = res.json[0]

    new_classes_names = [c["name"] for c in new_classes]
    returned_names = [c["name"] for c in rp_filtered["classes"]]
    assert new_classes_names[::-1] == returned_names  # classes should show up in reverse order


@pytest.mark.asyncio
@pytest.mark.xdist_group("sessions")  # Needs to run on the same worker as the rest of the sessions tests
async def test_get_single_pool_quota(
    sanic_client: SanicASGITestClient,
    valid_resource_pool_payload: dict[str, Any],
    admin_headers: dict[str, str],
    cluster: KindCluster,
) -> None:
    _, res = await create_rp(valid_resource_pool_payload, sanic_client)
    assert res.status_code == 201
    _, res = await sanic_client.get(
        "/api/data/resource_pools/1",
        headers=admin_headers,
    )
    assert res.status_code == 200
    assert res.json.get("name") == "test-name"
    _, res = await sanic_client.get(
        "/api/data/resource_pools/1/quota",
        headers=admin_headers,
    )
    assert res.status_code == 200
    assert res.json.get("cpu") == 100.0
    assert res.json.get("memory") == 100
    assert res.json.get("gpu") == 0
    assert res.json.get("id") is not None


@pytest.mark.asyncio
@pytest.mark.xdist_group("sessions")  # Needs to run on the same worker as the rest of the sessions tests
async def test_patch_quota(
    sanic_client: SanicASGITestClient,
    valid_resource_pool_payload: dict[str, Any],
    admin_headers: dict[str, str],
    cluster: KindCluster,
) -> None:
    _, res = await create_rp(valid_resource_pool_payload, sanic_client)
    assert res.status_code == 201
    _, res = await sanic_client.patch(
        "/api/data/resource_pools/1/quota", headers=admin_headers, data=json.dumps({"cpu": 1000})
    )
    assert res.status_code == 200
    assert res.json.get("cpu") == 1000


@pytest.mark.asyncio
@pytest.mark.xdist_group("sessions")  # Needs to run on the same worker as the rest of the sessions tests
async def test_put_quota(
    sanic_client: SanicASGITestClient,
    valid_resource_pool_payload: dict[str, Any],
    admin_headers: dict[str, str],
    cluster: KindCluster,
) -> None:
    _, res = await create_rp(valid_resource_pool_payload, sanic_client)
    assert res.status_code == 201
    _, res = await sanic_client.get(
        "/api/data/resource_pools/1/quota",
        headers=admin_headers,
    )
    assert res.status_code == 200
    quota = res.json
    quota = {**quota, "cpu": 1000, "memory": 1000, "gpu": 1000}
    _, res = await sanic_client.put("/api/data/resource_pools/1/quota", headers=admin_headers, data=json.dumps(quota))
    assert res.status_code == 200
    assert res.json == quota


@pytest.mark.asyncio
@pytest.mark.xdist_group("sessions")  # Needs to run on the same worker as the rest of the sessions tests
async def test_patch_resource_class(
    sanic_client: SanicASGITestClient,
    valid_resource_pool_payload: dict[str, Any],
    admin_headers: dict[str, str],
    cluster: KindCluster,
) -> None:
    _, res = await create_rp(valid_resource_pool_payload, sanic_client)
    assert res.status_code == 201
    _, res = await sanic_client.patch(
        "/api/data/resource_pools/1/classes/1", headers=admin_headers, data=json.dumps({"cpu": 5.0})
    )
    assert res.status_code == 200
    assert res.json.get("cpu") == 5.0


@pytest.mark.asyncio
@pytest.mark.xdist_group("sessions")  # Needs to run on the same worker as the rest of the sessions tests
async def test_put_resource_class(
    sanic_client: SanicASGITestClient,
    valid_resource_pool_payload: dict[str, Any],
    admin_headers: dict[str, str],
    cluster: KindCluster,
) -> None:
    _, res = await create_rp(valid_resource_pool_payload, sanic_client)
    assert res.status_code == 201
    assert len(res.json.get("classes", [])) == 2
    res_cls_payload = {**res.json.get("classes", [])[0], "cpu": 5.0}
    res_cls_expected_response = {**res.json.get("classes", [])[0], "cpu": 5.0}
    res_cls_payload.pop("id", None)
    _, res = await sanic_client.put(
        "/api/data/resource_pools/1/classes/1",
        headers=admin_headers,
        data=json.dumps(res_cls_payload),
    )
    assert res.status_code == 200
    assert res.json == res_cls_expected_response


@pytest.mark.asyncio
@pytest.mark.xdist_group("sessions")  # Needs to run on the same worker as the rest of the sessions tests
async def test_restricted_default_resource_pool_access(
    sanic_client: SanicASGITestClient,
    admin_headers: dict[str, str],
    valid_resource_pool_payload: dict[str, Any],
    cluster: KindCluster,
) -> None:
    valid_resource_pool_payload["default"] = True
    valid_resource_pool_payload["public"] = True
    del valid_resource_pool_payload["quota"]
    # Create default resource pool
    _, res = await create_rp(valid_resource_pool_payload, sanic_client)
    assert res.status_code == 201
    rp_default = res.json
    # Create a public non-default resource pool
    valid_resource_pool_payload["default"] = False
    _, res = await create_rp(valid_resource_pool_payload, sanic_client)
    assert res.status_code == 201
    rp_public = res.json
    # Get existing users
    _, res = await sanic_client.get("/api/data/users", headers=admin_headers)
    existing_users = res.json
    assert res.status_code == 200
    assert len(existing_users) >= 2
    # Restrict one user to not have access to the default pool
    no_default_user = existing_users[0]
    no_default_user_id = no_default_user["id"]
    no_default_access_token = json.dumps({"id": no_default_user_id})
    _, res = await sanic_client.delete(
        f"/api/data/resource_pools/{rp_default['id']}/users/{no_default_user_id}",
        headers=admin_headers,
    )
    assert res.status_code == 204
    # The other user in the db should be able to access the default pool
    default_access_user = existing_users[1]
    user_id = default_access_user["id"]
    access_token = json.dumps({"id": user_id})
    # Ensure non-authenticated users have access to the default pool
    _, res = await sanic_client.get(f"/api/data/resource_pools/{rp_default['id']}")
    assert res.status_code == 200
    assert res.json == rp_default
    # Ensure non-authenticated users have access to the public pool
    _, res = await sanic_client.get(f"/api/data/resource_pools/{rp_public['id']}")
    assert res.status_code == 200
    assert res.json == rp_public
    # Ensure that no_default_pool user cannot get the default pool
    _, res = await sanic_client.get(
        f"/api/data/resource_pools/{rp_default['id']}", headers={"Authorization": f"Bearer {no_default_access_token}"}
    )
    assert res.status_code == 404
    # Ensure that admin user can see the default pool
    _, res = await sanic_client.get(f"/api/data/resource_pools/{rp_default['id']}", headers=admin_headers)
    assert res.status_code == 200
    assert res.json == rp_default
    # Ensure that regular user can see the default pool
    _, res = await sanic_client.get(
        f"/api/data/resource_pools/{rp_default['id']}", headers={"Authorization": f"Bearer {access_token}"}
    )
    assert res.status_code == 200
    assert res.json == rp_default
    # Ensure that regular user can see the public pool
    _, res = await sanic_client.get(
        f"/api/data/resource_pools/{rp_public['id']}", headers={"Authorization": f"Bearer {access_token}"}
    )
    assert res.status_code == 200
    assert res.json == rp_public
    # Ensure that no_default user can see the public pool
    _, res = await sanic_client.get(
        f"/api/data/resource_pools/{rp_public['id']}", headers={"Authorization": f"Bearer {no_default_access_token}"}
    )
    assert res.status_code == 200
    assert res.json == rp_public


@pytest.mark.asyncio
@pytest.mark.xdist_group("sessions")  # Needs to run on the same worker as the rest of the sessions tests
async def test_restricted_default_resource_pool_access_changes(
    sanic_client: SanicASGITestClient,
    admin_headers: dict[str, str],
    valid_resource_pool_payload: dict[str, Any],
    cluster: KindCluster,
) -> None:
    valid_resource_pool_payload["default"] = True
    valid_resource_pool_payload["public"] = True
    del valid_resource_pool_payload["quota"]
    # Create default resource pool
    _, res = await create_rp(valid_resource_pool_payload, sanic_client)
    assert res.status_code == 201
    rp_default = res.json
    # Get existing users
    _, res = await sanic_client.get("/api/data/users", headers=admin_headers)
    existing_users = res.json
    assert res.status_code == 200
    assert len(existing_users) >= 2
    # Restrict one user to not have access to the default pool
    no_default_user = existing_users[0]
    no_default_user_id = no_default_user["id"]
    no_default_access_token = json.dumps({"id": no_default_user_id})
    _, res = await sanic_client.delete(
        f"/api/data/resource_pools/{rp_default['id']}/users/{no_default_user_id}",
        headers=admin_headers,
    )
    assert res.status_code == 204
    # Ensure that no_default_pool user cannot get the default pool
    _, res = await sanic_client.get(
        f"/api/data/resource_pools/{rp_default['id']}", headers={"Authorization": f"Bearer {no_default_access_token}"}
    )
    assert res.status_code == 404
    # Add the no_default user back to the default pool
    _, res = await sanic_client.post(
        f"/api/data/resource_pools/{rp_default['id']}/users",
        headers=admin_headers,
        data=json.dumps([{"id": no_default_user_id}]),
    )
    assert res.status_code == 201
    # Ensure that the user can now see the default pool
    _, res = await sanic_client.get(
        f"/api/data/resource_pools/{rp_default['id']}", headers={"Authorization": f"Bearer {no_default_access_token}"}
    )
    assert res.status_code == 200


@pytest.mark.asyncio
@pytest.mark.xdist_group("sessions")  # Needs to run on the same worker as the rest of the sessions tests
async def test_private_resource_pool_access(
    sanic_client: SanicASGITestClient,
    admin_headers: dict[str, str],
    valid_resource_pool_payload: dict[str, Any],
    cluster: KindCluster,
) -> None:
    valid_resource_pool_payload["default"] = False
    valid_resource_pool_payload["public"] = False
    # Create private resource pool
    _, res = await create_rp(valid_resource_pool_payload, sanic_client)
    assert res.status_code == 201
    rp_private = res.json
    # Get existing users
    _, res = await sanic_client.get("/api/data/users", headers=admin_headers)
    existing_users = res.json
    assert res.status_code == 200
    assert len(existing_users) >= 2
    # Select one user that has no access
    restricted_user = existing_users[0]
    restricted_user_id = restricted_user["id"]
    restricted_access_token = json.dumps({"id": restricted_user_id})
    # Give another user access to the private pool
    allowed_user = existing_users[1]
    allowed_user_id = allowed_user["id"]
    user_payload = [{"id": allowed_user_id}]
    allowed_access_token = json.dumps({"id": allowed_user_id})
    _, res = await sanic_client.post(
        f"/api/data/resource_pools/{rp_private['id']}/users",
        headers=admin_headers,
        data=json.dumps(user_payload),
    )
    assert res.status_code == 201
    # Ensure non-authenticated users cannot see the private pool
    _, res = await sanic_client.get(f"/api/data/resource_pools/{rp_private['id']}")
    assert res.status_code == 404
    # Ensure that a user that is not part of the private pool cannot see the pool
    _, res = await sanic_client.get(
        f"/api/data/resource_pools/{rp_private['id']}", headers={"Authorization": f"Bearer {restricted_access_token}"}
    )
    assert res.status_code == 404
    # Ensure that admin user can see the private pool
    _, res = await sanic_client.get(f"/api/data/resource_pools/{rp_private['id']}", headers=admin_headers)
    assert res.status_code == 200
    assert res.json == rp_private
    # Ensure that the user who is part of the private pool can see the pool
    _, res = await sanic_client.get(
        f"/api/data/resource_pools/{rp_private['id']}", headers={"Authorization": f"Bearer {allowed_access_token}"}
    )
    assert res.status_code == 200
    assert res.json == rp_private


@pytest.mark.asyncio
@pytest.mark.xdist_group("sessions")  # Needs to run on the same worker as the rest of the sessions tests
async def test_remove_resource_pool_users(
    sanic_client: SanicASGITestClient,
    admin_headers: dict[str, str],
    valid_resource_pool_payload: dict[str, Any],
    cluster: KindCluster,
) -> None:
    valid_resource_pool_payload["default"] = False
    valid_resource_pool_payload["public"] = False
    # Create private resource pool
    _, res = await create_rp(valid_resource_pool_payload, sanic_client)
    assert res.status_code == 201
    rp_private = res.json
    # Get existing users
    _, res = await sanic_client.get("/api/data/users", headers=admin_headers)
    existing_users = res.json
    assert res.status_code == 200
    assert len(existing_users) >= 3
    # Give another user access to the private pool
    allowed_user = existing_users[1]
    allowed_user2 = existing_users[2]
    allowed_user_id = allowed_user["id"]
    allowed_user2_id = allowed_user2["id"]
    user_payload = [{"id": allowed_user_id}, {"id": allowed_user2_id}]
    allowed_access_token = json.dumps({"id": allowed_user_id})
    _, res = await sanic_client.post(
        f"/api/data/resource_pools/{rp_private['id']}/users",
        headers=admin_headers,
        data=json.dumps(user_payload),
    )
    assert res.status_code == 201
    # Ensure that the user we added to the private pool can see the pool
    _, res = await sanic_client.get(
        f"/api/data/resource_pools/{rp_private['id']}", headers={"Authorization": f"Bearer {allowed_access_token}"}
    )
    assert res.status_code == 200
    assert res.json == rp_private
    # The added user should appear in the list of pool users
    _, res = await sanic_client.get(
        f"/api/data/resource_pools/{rp_private['id']}/users",
        headers=admin_headers,
    )
    assert res.status_code == 200
    assert len(res.json) == 2
    assert set([u["id"] for u in res.json]) == {allowed_user_id, allowed_user2_id}
    # Remove the user from the private pool
    _, res = await sanic_client.delete(
        f"/api/data/resource_pools/{rp_private['id']}/users/{allowed_user_id}",
        headers=admin_headers,
    )
    assert res.status_code == 204
    # The removed user cannot see the pool
    _, res = await sanic_client.get(
        f"/api/data/resource_pools/{rp_private['id']}", headers={"Authorization": f"Bearer {allowed_access_token}"}
    )
    assert res.status_code == 404
    # The removed user does not appear in the list of pool users
    _, res = await sanic_client.get(
        f"/api/data/resource_pools/{rp_private['id']}/users",
        headers=admin_headers,
    )
    assert res.status_code == 200
    assert len(res.json) == 1
    assert len([user for user in res.json if user.get("id") == allowed_user_id]) == 0
    # The remaining user can see the pool
    user2_access_token = json.dumps({"id": allowed_user2_id})
    user2_headers = {"Authorization": f"Bearer {user2_access_token}"}
    _, res = await sanic_client.get(
        f"/api/data/resource_pools/{rp_private['id']}",
        headers=user2_headers,
    )
    assert res.status_code == 200


@pytest.mark.asyncio
@pytest.mark.xdist_group("sessions")  # Needs to run on the same worker as the rest of the sessions tests
async def test_user_resource_pools(
    sanic_client: SanicASGITestClient,
    admin_headers: dict[str, str],
    valid_resource_pool_payload: dict[str, Any],
    cluster: KindCluster,
) -> None:
    # Create private resource pool
    valid_resource_pool_payload["default"] = False
    valid_resource_pool_payload["public"] = False
    _, res = await create_rp(valid_resource_pool_payload, sanic_client)
    assert res.status_code == 201
    rp_private = res.json
    # Create a public default resource pool
    valid_resource_pool_payload["default"] = True
    valid_resource_pool_payload["public"] = True
    del valid_resource_pool_payload["quota"]
    _, res = await create_rp(valid_resource_pool_payload, sanic_client)
    rp_public = res.json
    assert res.status_code == 201
    # Get existing users and pick 1 regular user to test with
    _, res = await sanic_client.get("/api/data/users", headers=admin_headers)
    existing_users = res.json
    assert res.status_code == 200
    assert len(existing_users) >= 1
    user = existing_users[0]
    user_id = user["id"]
    user_access_token = json.dumps({"id": user_id})
    user_headers = {"Authorization": f"Bearer {user_access_token}"}
    # Check that only the public default resource pool appears in the list of pools for the user
    _, res = await sanic_client.get(f"/api/data/users/{user_id}/resource_pools", headers=admin_headers)
    assert res.status_code == 200
    assert len(res.json) == 1
    assert res.json[0] == rp_public
    # Give access to the user to the private pool
    _, res = await sanic_client.post(
        f"/api/data/users/{user_id}/resource_pools",
        headers=admin_headers,
        json=[rp_private["id"]],
    )
    assert res.status_code == 201
    # Check the user can see the private pool
    _, res = await sanic_client.get(f"/api/data/resource_pools/{rp_private['id']}", headers=user_headers)
    assert res.status_code == 200
    assert res.json == rp_private
    # Check the resource pool appears in the list of pools for the user
    _, res = await sanic_client.get(f"/api/data/users/{user_id}/resource_pools", headers=admin_headers)
    assert res.status_code == 200
    assert len(res.json) == 2
    added_pool = [i for i in res.json if not i["public"]][0]
    assert added_pool == rp_private
    # Set the resource pools the user has access to with a put request
    _, res = await sanic_client.put(
        f"/api/data/users/{user_id}/resource_pools",
        headers=admin_headers,
        json=[rp_public["id"]],
    )
    assert res.status_code == 200
    # Check only the public pool appears in the list of pools for the user
    _, res = await sanic_client.get(f"/api/data/users/{user_id}/resource_pools", headers=admin_headers)
    assert res.status_code == 200
    assert len(res.json) == 1
    assert res.json[0] == rp_public
    # Check the user can only see the public pool
    _, res = await sanic_client.get("/api/data/resource_pools", headers=user_headers)
    assert res.status_code == 200
    assert len(res.json) == 1
    assert res.json[0]["id"] == rp_public["id"]


@pytest.mark.asyncio
@pytest.mark.xdist_group("sessions")  # Needs to run on the same worker as the rest of the sessions tests
async def test_adding_existing_user_does_not_fail(
    sanic_client: SanicASGITestClient,
    admin_headers: dict[str, str],
    valid_resource_pool_payload: dict[str, Any],
    member_1_user,
    cluster: KindCluster,
):
    # Create private resource pool
    valid_resource_pool_payload["default"] = False
    valid_resource_pool_payload["public"] = False
    _, res = await create_rp(valid_resource_pool_payload, sanic_client)
    assert res.status_code == 201
    rp_private = res.json
    user_id = member_1_user.id

    # Give access to the user to the private pool
    _, res = await sanic_client.post(
        f"/api/data/users/{user_id}/resource_pools", headers=admin_headers, json=[rp_private["id"]]
    )
    assert res.status_code == 201

    # Re-add the same user to the resource pool
    _, res = await sanic_client.post(
        f"/api/data/users/{user_id}/resource_pools", headers=admin_headers, json=[rp_private["id"]]
    )
    assert res.status_code == 201

    # Re-add the same user to the resource pool using PUT
    _, res = await sanic_client.put(
        f"/api/data/users/{user_id}/resource_pools", headers=admin_headers, json=[rp_private["id"]]
    )
    assert res.status_code == 200

    # Re-add the same user to the resource pool using the resource pool endpoint
    _, res = await sanic_client.post(
        f"/api/data/resource_pools/{rp_private['id']}/users", headers=admin_headers, json=[{"id": user_id}]
    )
    assert res.status_code == 201

    # Re-add the same user to the resource pool using the resource pool endpoint PUT
    _, res = await sanic_client.put(
        f"/api/data/resource_pools/{rp_private['id']}/users", headers=admin_headers, json=[{"id": user_id}]
    )
    assert res.status_code == 200


@pytest.mark.asyncio
@pytest.mark.xdist_group("sessions")  # Needs to run on the same worker as the rest of the sessions tests
async def test_patch_tolerations(
    sanic_client: SanicASGITestClient,
    admin_headers: dict[str, str],
    valid_resource_pool_payload: dict[str, Any],
    cluster: KindCluster,
) -> None:
    valid_resource_pool_payload["classes"][0]["tolerations"] = ["toleration1"]
    _, res = await create_rp(valid_resource_pool_payload, sanic_client)
    assert res.status_code == 201
    rp = res.json
    rp_id = rp["id"]
    assert len(rp["classes"]) > 0
    res_class = [i for i in rp["classes"] if len(i.get("tolerations", [])) > 0][0]
    res_class_id = res_class["id"]
    assert len(res_class["tolerations"]) == 1
    # Patch in a 2nd toleration
    _, res = await sanic_client.patch(
        f"/api/data/resource_pools/{rp_id}/classes/{res_class_id}",
        headers=admin_headers,
        data=json.dumps({"tolerations": ["toleration1", "toleration2"]}),
    )
    assert res.status_code == 200
    assert "toleration2" in res.json["tolerations"]
    # Adding the same toleration again does not add copies of it
    _, res = await sanic_client.patch(
        f"/api/data/resource_pools/{rp_id}/classes/{res_class_id}",
        headers=admin_headers,
        data=json.dumps({"tolerations": ["toleration1", "toleration2", "toleration1"]}),
    )
    assert res.status_code == 200
    assert len(res.json["tolerations"]) == 2
    # Get the resource class to make sure that toleration is truly in the DB
    _, res = await sanic_client.get(
        f"/api/data/resource_pools/{rp_id}/classes/{res_class_id}",
        headers=admin_headers,
    )
    assert res.status_code == 200
    assert "toleration2" in res.json["tolerations"]
    assert "toleration1" in res.json["tolerations"]
    assert len(res.json["tolerations"]) == 2


@pytest.mark.asyncio
@pytest.mark.xdist_group("sessions")  # Needs to run on the same worker as the rest of the sessions tests
async def test_patch_affinities(
    sanic_client: SanicASGITestClient,
    admin_headers: dict[str, str],
    valid_resource_pool_payload: dict[str, Any],
    cluster: KindCluster,
) -> None:
    valid_resource_pool_payload["classes"][0]["node_affinities"] = [{"key": "affinity1"}]
    _, res = await create_rp(valid_resource_pool_payload, sanic_client)
    assert res.status_code == 201
    rp = res.json
    rp_id = rp["id"]
    assert len(rp["classes"]) > 0
    res_class = [i for i in rp["classes"] if len(i.get("node_affinities", [])) > 0][0]
    res_class_id = res_class["id"]
    assert len(res_class["node_affinities"]) == 1
    assert res_class["node_affinities"][0] == {"key": "affinity1", "required_during_scheduling": False}
    # Patch in a 2nd affinity
    new_affinity = {"key": "affinity2"}
    _, res = await sanic_client.patch(
        f"/api/data/resource_pools/{rp_id}/classes/{res_class_id}",
        headers=admin_headers,
        data=json.dumps({"node_affinities": res_class["node_affinities"] + [new_affinity]}),
    )
    assert res.status_code == 200
    assert len(res.json["node_affinities"]) == 2
    inserted_affinity = next(filter(lambda x: x["key"] == new_affinity["key"], res.json["node_affinities"]))
    assert inserted_affinity["key"] == new_affinity["key"]
    assert not inserted_affinity["required_during_scheduling"]
    # Adding the same affinity again does not add copies of it
    _, res = await sanic_client.patch(
        f"/api/data/resource_pools/{rp_id}/classes/{res_class_id}",
        headers=admin_headers,
        data=json.dumps({"node_affinities": res_class["node_affinities"] + [new_affinity, new_affinity]}),
    )
    assert res.status_code == 200
    assert len(res.json["node_affinities"]) == 2
    # Updating an affinity required_during_scheduling field
    new_affinity = {"key": "affinity2", "required_during_scheduling": True}
    _, res = await sanic_client.patch(
        f"/api/data/resource_pools/{rp_id}/classes/{res_class_id}",
        headers=admin_headers,
        data=json.dumps({"node_affinities": res_class["node_affinities"] + [new_affinity]}),
    )
    assert res.status_code == 200
    assert len(res.json["node_affinities"]) == 2
    inserted_affinity = next(filter(lambda x: x["key"] == new_affinity["key"], res.json["node_affinities"]))
    assert inserted_affinity["required_during_scheduling"]
    # Get the resource class to make sure that node affinities are truly in the DB
    _, res = await sanic_client.get(
        f"/api/data/resource_pools/{rp_id}/classes/{res_class_id}",
        headers=admin_headers,
    )
    assert res.status_code == 200
    assert len(res.json["node_affinities"]) == 2


@pytest.mark.asyncio
@pytest.mark.xdist_group("sessions")  # Needs to run on the same worker as the rest of the sessions tests
async def test_remove_all_tolerations_put(
    sanic_client: SanicASGITestClient,
    admin_headers: dict[str, str],
    valid_resource_pool_payload: dict[str, Any],
    cluster: KindCluster,
) -> None:
    valid_resource_pool_payload["classes"][0]["tolerations"] = ["toleration1"]
    _, res = await create_rp(valid_resource_pool_payload, sanic_client)
    assert res.status_code == 201
    rp = res.json
    rp_id = rp["id"]
    assert len(rp["classes"]) > 0
    res_class = [i for i in rp["classes"] if len(i.get("tolerations", [])) > 0][0]
    res_class_id = res_class["id"]
    assert len(res_class["tolerations"]) == 1
    assert res_class["tolerations"][0] == "toleration1"
    new_class = deepcopy(res_class)
    new_class.pop("id")
    new_class["tolerations"] = []
    _, res = await sanic_client.put(
        f"/api/data/resource_pools/{rp_id}/classes/{res_class_id}",
        headers=admin_headers,
        data=json.dumps(new_class),
    )
    assert res.status_code == 200
    assert not res.json.get("tolerations")
    _, res = await sanic_client.get(
        f"/api/data/resource_pools/{rp_id}/classes/{res_class_id}",
        headers=admin_headers,
    )
    assert res.status_code == 200
    assert res.json["tolerations"] == []


@pytest.mark.asyncio
@pytest.mark.xdist_group("sessions")  # Needs to run on the same worker as the rest of the sessions tests
async def test_remove_all_affinities_put(
    sanic_client: SanicASGITestClient,
    admin_headers: dict[str, str],
    valid_resource_pool_payload: dict[str, Any],
    cluster: KindCluster,
) -> None:
    valid_resource_pool_payload["classes"][0]["node_affinities"] = [{"key": "affinity1"}]
    _, res = await create_rp(valid_resource_pool_payload, sanic_client)
    assert res.status_code == 201
    rp = res.json
    rp_id = rp["id"]
    assert len(rp["classes"]) > 0
    res_class = [i for i in rp["classes"] if len(i.get("node_affinities", [])) > 0][0]
    res_class_id = res_class["id"]
    assert len(res_class["node_affinities"]) == 1
    assert res_class["node_affinities"][0] == {"key": "affinity1", "required_during_scheduling": False}
    new_class = deepcopy(res_class)
    new_class.pop("id")
    new_class["node_affinities"] = []
    _, res = await sanic_client.put(
        f"/api/data/resource_pools/{rp_id}/classes/{res_class_id}",
        headers=admin_headers,
        data=json.dumps(new_class),
    )
    assert res.status_code == 200
    assert not res.json.get("node_affinities")
    _, res = await sanic_client.get(
        f"/api/data/resource_pools/{rp_id}/classes/{res_class_id}",
        headers=admin_headers,
    )
    assert res.status_code == 200
    assert res.json["node_affinities"] == []


@pytest.mark.asyncio
@pytest.mark.xdist_group("sessions")  # Needs to run on the same worker as the rest of the sessions tests
async def test_put_tolerations(
    sanic_client: SanicASGITestClient,
    admin_headers: dict[str, str],
    valid_resource_pool_payload: dict[str, Any],
    cluster: KindCluster,
) -> None:
    valid_resource_pool_payload["classes"][0]["tolerations"] = ["toleration1"]
    _, res = await create_rp(valid_resource_pool_payload, sanic_client)
    assert res.status_code == 201, res.text
    rp = res.json
    rp_id = rp["id"]
    assert len(rp["classes"]) > 0
    res_class = [i for i in rp["classes"] if len(i.get("tolerations", [])) > 0][0]
    res_class_id = res_class["id"]
    assert len(res_class["tolerations"]) == 1
    assert res_class["tolerations"][0] == "toleration1"
    new_class = deepcopy(res_class)
    new_class.pop("id")
    new_class["tolerations"] = ["toleration2", "toleration3"]
    _, res = await sanic_client.put(
        f"/api/data/resource_pools/{rp_id}/classes/{res_class_id}",
        headers=admin_headers,
        data=json.dumps(new_class),
    )
    assert res.status_code == 200, res.text
    assert res.json["tolerations"] == ["toleration2", "toleration3"]
    _, res = await sanic_client.get(
        f"/api/data/resource_pools/{rp_id}/classes/{res_class_id}",
        headers=admin_headers,
    )
    assert res.status_code == 200, res.text
    assert res.json["tolerations"] == ["toleration2", "toleration3"]


@pytest.mark.asyncio
@pytest.mark.xdist_group("sessions")  # Needs to run on the same worker as the rest of the sessions tests
async def test_put_affinities(
    sanic_client: SanicASGITestClient,
    admin_headers: dict[str, str],
    valid_resource_pool_payload: dict[str, Any],
    cluster: KindCluster,
) -> None:
    valid_resource_pool_payload["classes"][0]["node_affinities"] = [{"key": "affinity1"}]
    _, res = await create_rp(valid_resource_pool_payload, sanic_client)
    assert res.status_code == 201
    rp = res.json
    rp_id = rp["id"]
    assert len(rp["classes"]) > 0
    res_class = [i for i in rp["classes"] if len(i.get("node_affinities", [])) > 0][0]
    res_class_id = res_class["id"]
    assert len(res_class["node_affinities"]) == 1
    assert res_class["node_affinities"][0] == {"key": "affinity1", "required_during_scheduling": False}
    new_class = deepcopy(res_class)
    new_class.pop("id")
    new_class["node_affinities"] = [{"key": "affinity1", "required_during_scheduling": True}, {"key": "affinity2"}]
    _, res = await sanic_client.put(
        f"/api/data/resource_pools/{rp_id}/classes/{res_class_id}",
        headers=admin_headers,
        data=json.dumps(new_class),
    )
    assert res.status_code == 200
    assert res.json["node_affinities"] == [
        {"key": "affinity1", "required_during_scheduling": True},
        {"key": "affinity2", "required_during_scheduling": False},
    ]
    _, res = await sanic_client.get(
        f"/api/data/resource_pools/{rp_id}/classes/{res_class_id}",
        headers=admin_headers,
    )
    assert res.status_code == 200
    assert res.json["node_affinities"] == [
        {"key": "affinity1", "required_during_scheduling": True},
        {"key": "affinity2", "required_during_scheduling": False},
    ]


@pytest.mark.asyncio
@pytest.mark.xdist_group("sessions")  # Needs to run on the same worker as the rest of the sessions tests
async def test_get_all_tolerations(
    sanic_client: SanicASGITestClient,
    admin_headers: dict[str, str],
    valid_resource_pool_payload: dict[str, Any],
    cluster: KindCluster,
) -> None:
    valid_resource_pool_payload["classes"][0]["tolerations"] = ["toleration1"]
    _, res = await create_rp(valid_resource_pool_payload, sanic_client)
    assert res.status_code == 201
    rp = res.json
    rp_id = rp["id"]
    assert len(rp["classes"]) > 0
    res_class = [i for i in rp["classes"] if len(i.get("tolerations", [])) > 0][0]
    res_class_id = res_class["id"]
    _, res = await sanic_client.get(
        f"/api/data/resource_pools/{rp_id}/classes/{res_class_id}/tolerations",
        headers=admin_headers,
    )
    assert res.status_code == 200
    assert res.json == ["toleration1"]


@pytest.mark.asyncio
@pytest.mark.xdist_group("sessions")  # Needs to run on the same worker as the rest of the sessions tests
async def test_get_all_affinities(
    sanic_client: SanicASGITestClient,
    admin_headers: dict[str, str],
    valid_resource_pool_payload: dict[str, Any],
    cluster: KindCluster,
) -> None:
    valid_resource_pool_payload["classes"][0]["node_affinities"] = [{"key": "affinity1"}]
    _, res = await create_rp(valid_resource_pool_payload, sanic_client)
    assert res.status_code == 201
    rp = res.json
    rp_id = rp["id"]
    assert len(rp["classes"]) > 0
    res_class = [i for i in rp["classes"] if len(i.get("node_affinities", [])) > 0][0]
    res_class_id = res_class["id"]
    _, res = await sanic_client.get(
        f"/api/data/resource_pools/{rp_id}/classes/{res_class_id}/node_affinities",
        headers=admin_headers,
    )
    assert res.status_code == 200
    assert res.json == [{"key": "affinity1", "required_during_scheduling": False}]


@pytest.mark.asyncio
@pytest.mark.xdist_group("sessions")  # Needs to run on the same worker as the rest of the sessions tests
async def test_delete_all_affinities(
    sanic_client: SanicASGITestClient,
    admin_headers: dict[str, str],
    valid_resource_pool_payload: dict[str, Any],
    cluster: KindCluster,
) -> None:
    valid_resource_pool_payload["classes"][0]["node_affinities"] = [{"key": "affinity1"}]
    _, res = await create_rp(valid_resource_pool_payload, sanic_client)
    assert res.status_code == 201
    rp = res.json
    rp_id = rp["id"]
    assert len(rp["classes"]) > 0
    res_class = rp["classes"][0]
    res_class_id = res_class["id"]
    _, res = await sanic_client.delete(
        f"/api/data/resource_pools/{rp_id}/classes/{res_class_id}/node_affinities",
        headers=admin_headers,
    )
    assert res.status_code == 204
    _, res = await sanic_client.get(
        f"/api/data/resource_pools/{rp_id}/classes/{res_class_id}/node_affinities",
        headers=admin_headers,
    )
    assert res.status_code == 200
    assert res.json == []


@pytest.mark.asyncio
@pytest.mark.xdist_group("sessions")  # Needs to run on the same worker as the rest of the sessions tests
async def test_delete_all_tolerations(
    sanic_client: SanicASGITestClient,
    admin_headers: dict[str, str],
    valid_resource_pool_payload: dict[str, Any],
    cluster: KindCluster,
) -> None:
    valid_resource_pool_payload["classes"][0]["tolerations"] = ["toleration1"]
    _, res = await create_rp(valid_resource_pool_payload, sanic_client)
    assert res.status_code == 201
    rp = res.json
    rp_id = rp["id"]
    assert len(rp["classes"]) > 0
    res_class = rp["classes"][0]
    res_class_id = res_class["id"]
    _, res = await sanic_client.delete(
        f"/api/data/resource_pools/{rp_id}/classes/{res_class_id}/tolerations",
        headers=admin_headers,
    )
    assert res.status_code == 204
    _, res = await sanic_client.get(
        f"/api/data/resource_pools/{rp_id}/classes/{res_class_id}/tolerations",
        headers=admin_headers,
    )
    assert res.status_code == 200
    assert res.json == []


resource_pool_payload_2 = {
    "name": "test-name",
    "classes": [
        {
            "cpu": 1.0,
            "memory": 10,
            "gpu": 0,
            "name": "test-class-name",
            "max_storage": 100,
            "default_storage": 1,
            "default": True,
            "node_affinities": [],
            "tolerations": [],
        }
    ],
    "quota": {"cpu": 100.0, "memory": 100, "gpu": 0},
    "default": False,
    "public": True,
    "idle_threshold": 86400,
    "hibernation_threshold": 99999,
    "hibernation_warning_period": 888,
}

cluster_payload = {
    "config_name": "a-filename.yaml",
    "name": "test-cluster-post",
}


async def _resource_pools_request(
    sanic_client: SanicASGITestClient,
    method: str,
    admin_headers: dict[str, str],
    expected_status_code: int,
    auth: bool,
    resource_pool_id: int | None,
    payload: dict | None,
) -> None:
    base_url = "/api/data/resource_pools"

    input_payload = deepcopy(payload)
    check_payload = None
    if resource_pool_id is None:
        tmp = deepcopy(resource_pool_payload_2)
        if "cluster_id" in input_payload and input_payload["cluster_id"] == "replace-me":
            _, res = await sanic_client.post("/api/data/clusters/", headers=admin_headers, json=cluster_payload)
            assert res.status_code == 201, res.text

            input_payload["cluster_id"] = res.json["id"]
            tmp["cluster_id"] = res.json["id"]

        _, res = await sanic_client.post(base_url, headers=admin_headers, json=tmp)
        assert res.status_code == 201, res.text
        rp = res.json
        resource_pool_id = rp["id"]

        if method == "PUT" and "id" not in input_payload["quota"]:
            input_payload["quota"]["id"] = rp["quota"]["id"]

        for i, c in enumerate(input_payload["classes"]):
            if "id" not in c:
                c["id"] = rp["classes"][i]["id"]

        if "platform" not in input_payload:
            input_payload["platform"] = "linux/amd64"

        check_payload = deepcopy(input_payload)

        if "id" not in check_payload:
            check_payload["id"] = resource_pool_id
        if "id" not in check_payload["quota"]:
            check_payload["quota"]["id"] = rp["quota"]["id"]

    url = f"{base_url}/{resource_pool_id}"

    if auth:
        _, res = await sanic_client.request(url=url, method=method, headers=admin_headers, json=input_payload)
    else:
        _, res = await sanic_client.request(url=url, method=method, json=input_payload)

    assert res.status_code == expected_status_code, res.text
    if res.is_success and check_payload is not None:
        assert res.json == check_payload, res.json


put_patch_common_test_inputs = [
    (401, False, -1, None),
    (422, True, -1, None),
    (401, False, 0, None),
    (422, True, 0, None),
    (401, False, -1, resource_pool_payload_2),
    (422, True, -1, resource_pool_payload_2),
    (401, False, 0, resource_pool_payload_2),
    (422, True, 0, resource_pool_payload_2),
    (401, False, 100, resource_pool_payload_2),
    (422, True, 100, resource_pool_payload_2),
    (401, False, None, resource_pool_payload_2),
    (200, True, None, resource_pool_payload_2),
]


@pytest.mark.parametrize("expected_status_code,auth,resource_pool_id,payload", put_patch_common_test_inputs)
@pytest.mark.asyncio
@pytest.mark.xdist_group("sessions")  # Needs to run on the same worker as the rest of the sessions tests
async def test_resource_pools_put(
    sanic_client: SanicASGITestClient,
    admin_headers: dict[str, str],
    expected_status_code: int,
    auth: bool,
    resource_pool_id: int,
    payload: dict | None,
    cluster: KindCluster,
) -> None:
    await _resource_pools_request(
        sanic_client, "PUT", admin_headers, expected_status_code, auth, resource_pool_id, payload
    )


@pytest.mark.parametrize("expected_status_code,auth,resource_pool_id,payload", put_patch_common_test_inputs)
@pytest.mark.asyncio
@pytest.mark.xdist_group("sessions")  # Needs to run on the same worker as the rest of the sessions tests
async def test_resource_pools_patch(
    sanic_client: SanicASGITestClient,
    admin_headers: dict[str, str],
    expected_status_code: int,
    auth: bool,
    resource_pool_id: int | None,
    payload: dict | None,
    cluster: KindCluster,
) -> None:
    await _resource_pools_request(
        sanic_client, "PATCH", admin_headers, expected_status_code, auth, resource_pool_id, payload
    )


@pytest.mark.parametrize(
    "expected_status_code,auth,resource_pool_id",
    [
        (401, False, -1),
        (422, True, -1),
        (204, True, 0),
        (204, True, 10),
        (401, False, None),
        (204, True, None),
    ],
)
@pytest.mark.asyncio
@pytest.mark.xdist_group("sessions")  # Needs to run on the same worker as the rest of the sessions tests
async def test_resource_pools_delete(
    sanic_client: SanicASGITestClient,
    admin_headers: dict[str, str],
    expected_status_code: int,
    auth: bool,
    resource_pool_id: str | None,
    cluster: KindCluster,
) -> None:
    base_url = "/api/data/resource_pools"

    if resource_pool_id is None:
        _, res = await sanic_client.post(base_url, headers=admin_headers, json=resource_pool_payload_2)
        assert res.status_code == 201, res.text
        resource_pool_id = res.json["id"]

    url = f"{base_url}/{resource_pool_id}"

    if auth:
        _, res = await sanic_client.delete(url, headers=admin_headers)
    else:
        _, res = await sanic_client.delete(url)
    assert res.status_code == expected_status_code, res.text


@pytest.mark.asyncio
@pytest.mark.xdist_group("sessions")  # Needs to run on the same worker as the rest of the sessions tests
async def test_resource_pool_patch_remote(
    sanic_client: SanicASGITestClient,
    admin_headers: dict[str, str],
    cluster: KindCluster,
) -> None:
    # Create a provider
    provider_payload = {
        "id": "some-provider",
        "kind": "gitlab",
        "client_id": "some-client-id",
        "display_name": "my oauth2 application",
        "scope": "api",
        "url": "https://example.org",
    }
    _, res = await sanic_client.post("/api/data/oauth2/providers", headers=admin_headers, json=provider_payload)
    assert res.status_code == 201, res.text

    # First, create a non-remote resource pool
    payload = deepcopy(resource_pool_payload_2)
    if "cluster_id" in payload:
        payload["cluster_id"] = None

    _, res = await create_rp(payload, sanic_client)
    assert res.status_code == 201, res.text
    rp_id = res.json["id"]

    # Patch with the remote configuration
    patch = {
        "default": False,
        "public": False,
        "remote": {
            "kind": "firecrest",
            "provider_id": provider_payload["id"],
            "api_url": "https://example.org",
            "system_name": "my-system",
        },
    }

    _, res = await sanic_client.patch(f"/api/data/resource_pools/{rp_id}", headers=admin_headers, json=patch)
    assert res.status_code == 200, res.text
    assert res.json is not None
    rp = res.json
    assert rp.get("remote") == {
        "kind": "firecrest",
        "provider_id": provider_payload["id"],
        "api_url": "https://example.org",
        "system_name": "my-system",
    }

    # Patch to reset the resource pool
    patch = {"default": False, "public": False, "remote": {}}

    _, res = await sanic_client.patch(f"/api/data/resource_pools/{rp_id}", headers=admin_headers, json=patch)
    assert res.status_code == 200, res.text
    assert res.json is not None
    rp = res.json
    assert "remote" not in rp


@pytest.mark.asyncio
@pytest.mark.xdist_group("sessions")  # Needs to run on the same worker as the rest of the sessions tests
async def test_resource_pool_patch_platform(
    sanic_client: SanicASGITestClient,
    admin_headers: dict[str, str],
    cluster: KindCluster,
) -> None:
    # First, create a resource pool with the default runtime platform
    payload = deepcopy(resource_pool_payload_2)
    if "cluster_id" in payload:
        payload["cluster_id"] = None

    _, res = await create_rp(payload, sanic_client)
    assert res.status_code == 201, res.text
    rp_id = res.json["id"]
    rp = res.json
    assert rp.get("platform") == "linux/amd64"

    # Patch with a different runtime platform
    patch = {"platform": "linux/arm64"}

    _, res = await sanic_client.patch(f"/api/data/resource_pools/{rp_id}", headers=admin_headers, json=patch)
    assert res.status_code == 200, res.text
    assert res.json is not None
    rp = res.json
    assert rp.get("platform") == "linux/arm64"

    # Put to reset the resource pool
    put = deepcopy(resource_pool_payload_2)
    put["quota"] = rp["quota"]
    put["classes"] = rp["classes"]
    put["platform"] = "linux/amd64"

    _, res = await sanic_client.put(f"/api/data/resource_pools/{rp_id}", headers=admin_headers, json=put)
    assert res.status_code == 200, res.text
    assert res.json is not None
    rp = res.json
    assert rp.get("platform") == "linux/amd64"


@pytest.mark.asyncio
@pytest.mark.xdist_group("sessions")  # Needs to run on the same worker as the rest of the sessions tests
async def test_resource_pool_empty_patch_noop(
    sanic_client: SanicASGITestClient,
    admin_headers: dict[str, str],
    cluster: KindCluster,
) -> None:
    # First, create a resource pool
    payload = deepcopy(resource_pool_payload_2)
    if "cluster_id" in payload:
        payload["cluster_id"] = None
    payload["public"] = True

    _, res = await create_rp(payload, sanic_client)
    assert res.status_code == 201, res.text
    rp_id = res.json["id"]
    original_rp = res.json

    # Patch with an empty patch
    patch = {}

    _, res = await sanic_client.patch(f"/api/data/resource_pools/{rp_id}", headers=admin_headers, json=patch)
    assert res.status_code == 200, res.text
    assert res.json is not None
    rp = res.json
    assert rp == original_rp


@pytest.mark.asyncio
@pytest.mark.xdist_group("sessions")  # Needs to run on the same worker as the rest of the sessions tests
async def test_resource_class_empty_patch_noop(
    sanic_client: SanicASGITestClient,
    admin_headers: dict[str, str],
    cluster: KindCluster,
) -> None:
    # First, create a resource pool
    payload = deepcopy(resource_pool_payload_2)
    if "cluster_id" in payload:
        payload["cluster_id"] = None
    payload["public"] = True

    _, res = await create_rp(payload, sanic_client)
    assert res.status_code == 201, res.text
    rp_id = res.json["id"]

    # Get the default class in the pool
    default_rc = None
    for rc in res.json.get("classes", []):
        if rc.get("default"):
            default_rc = rc
    assert default_rc is not None
    assert default_rc.get("id") != ""
    rc_id = default_rc["id"]

    # Patch with an empty patch
    patch = {}

    _, res = await sanic_client.patch(
        f"/api/data/resource_pools/{rp_id}/classes/{rc_id}", headers=admin_headers, json=patch
    )
    assert res.status_code == 200, res.text
    assert res.json is not None
    rc = res.json
    assert rc == default_rc
