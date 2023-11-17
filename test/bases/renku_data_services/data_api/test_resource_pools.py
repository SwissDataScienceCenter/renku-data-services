import json
from test.bases.renku_data_services.data_api.utils import create_rp
from typing import Any, Dict

import pytest
from sanic import Sanic
from sanic_testing.testing import SanicASGITestClient

from renku_data_services.config import Config
from renku_data_services.data_api.app import register_all_handlers

_valid_resource_pool_payload: Dict[str, Any] = {
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
}


@pytest.fixture
def valid_resource_pool_payload() -> Dict[str, Any]:
    return _valid_resource_pool_payload


@pytest.fixture
def test_client(app_config: Config) -> SanicASGITestClient:
    app = Sanic(app_config.app_name)
    app = register_all_handlers(app, app_config)
    return SanicASGITestClient(app)


@pytest.fixture
def admin_user_headers() -> Dict[str, str]:
    return {"Authorization": 'Bearer {"is_admin": true}'}


@pytest.mark.parametrize(
    "payload,expected_status_code",
    [
        (
            _valid_resource_pool_payload,
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
    ],
)
@pytest.mark.asyncio
async def test_resource_pool_creation(
    test_client: SanicASGITestClient,
    payload: Dict[str, Any],
    expected_status_code: int,
):
    _, res = await create_rp(payload, test_client)
    assert res.status_code == expected_status_code


@pytest.mark.asyncio
async def test_get_single_pool_quota(
    test_client: SanicASGITestClient, valid_resource_pool_payload: Dict[str, Any], admin_user_headers: Dict[str, str]
):
    _, res = await create_rp(valid_resource_pool_payload, test_client)
    assert res.status_code == 201
    _, res = await test_client.get(
        "/api/data/resource_pools/1",
        headers=admin_user_headers,
    )
    assert res.status_code == 200
    assert res.json.get("name") == "test-name"
    _, res = await test_client.get(
        "/api/data/resource_pools/1/quota",
        headers=admin_user_headers,
    )
    assert res.status_code == 200
    assert res.json.get("cpu") == 100.0
    assert res.json.get("memory") == 100
    assert res.json.get("gpu") == 0
    assert res.json.get("id") is not None


@pytest.mark.asyncio
async def test_patch_quota(
    test_client: SanicASGITestClient, valid_resource_pool_payload: Dict[str, Any], admin_user_headers: Dict[str, str]
):
    _, res = await create_rp(valid_resource_pool_payload, test_client)
    assert res.status_code == 201
    _, res = await test_client.patch(
        "/api/data/resource_pools/1/quota", headers=admin_user_headers, data=json.dumps({"cpu": 1000})
    )
    assert res.status_code == 200
    assert res.json.get("cpu") == 1000


@pytest.mark.asyncio
async def test_put_quota(
    test_client: SanicASGITestClient, valid_resource_pool_payload: Dict[str, Any], admin_user_headers: Dict[str, str]
):
    _, res = await create_rp(valid_resource_pool_payload, test_client)
    assert res.status_code == 201
    _, res = await test_client.get(
        "/api/data/resource_pools/1/quota",
        headers=admin_user_headers,
    )
    assert res.status_code == 200
    quota = res.json
    quota = {**quota, "cpu": 1000, "memory": 1000, "gpu": 1000}
    _, res = await test_client.put(
        "/api/data/resource_pools/1/quota", headers=admin_user_headers, data=json.dumps(quota)
    )
    assert res.status_code == 200
    assert res.json == quota


@pytest.mark.asyncio
async def test_patch_resource_class(
    test_client: SanicASGITestClient, valid_resource_pool_payload: Dict[str, Any], admin_user_headers: Dict[str, str]
):
    _, res = await create_rp(valid_resource_pool_payload, test_client)
    assert res.status_code == 201
    _, res = await test_client.patch(
        "/api/data/resource_pools/1/classes/1", headers=admin_user_headers, data=json.dumps({"cpu": 5.0})
    )
    assert res.status_code == 200
    assert res.json.get("cpu") == 5.0


@pytest.mark.asyncio
async def test_put_resource_class(
    test_client: SanicASGITestClient, valid_resource_pool_payload: Dict[str, Any], admin_user_headers: Dict[str, str]
):
    _, res = await create_rp(valid_resource_pool_payload, test_client)
    assert res.status_code == 201
    assert len(res.json.get("classes", [])) == 1
    res_cls_payload = {**res.json.get("classes", [])[0], "cpu": 5.0}
    res_cls_expected_response = {**res.json.get("classes", [])[0], "cpu": 5.0}
    res_cls_payload.pop("id", None)
    _, res = await test_client.put(
        "/api/data/resource_pools/1/classes/1",
        headers=admin_user_headers,
        data=json.dumps(res_cls_payload),
    )
    assert res.status_code == 200
    assert res.json == res_cls_expected_response


@pytest.mark.asyncio
async def test_post_users(test_client: SanicASGITestClient, admin_user_headers: Dict[str, str]):
    user_payloads = [
        {"id": "keycloak-id-1"},
        {"id": "keycloak-id-2", "no_default_access": True},
    ]
    for payload in user_payloads:
        _, res = await test_client.post("/api/data/users", headers=admin_user_headers, data=json.dumps(payload))
        assert res.status_code == 201
        assert res.json["id"] == payload["id"]
        assert res.json["no_default_access"] == payload.get("no_default_access", False)


@pytest.mark.asyncio
async def test_patch_put_user(test_client: SanicASGITestClient, admin_user_headers: Dict[str, str]):
    user_id = "keycloak-id-1"
    user_payload = {"id": user_id}
    headers = admin_user_headers
    _, res = await test_client.post("/api/data/users", headers=headers, data=json.dumps(user_payload))
    assert res.status_code == 201
    assert res.json["id"] == user_id
    assert res.json["no_default_access"] == user_payload.get("no_default_access", False)
    _, res = await test_client.put(
        f"/api/data/users/{user_id}", headers=headers, data=json.dumps({"no_default_access": True})
    )
    assert res.status_code == 200
    assert res.json["id"] == user_id
    assert res.json["no_default_access"]
    _, res = await test_client.patch(
        f"/api/data/users/{user_id}", headers=headers, data=json.dumps({"no_default_access": False})
    )
    assert res.status_code == 200
    assert res.json["id"] == user_id
    assert not res.json["no_default_access"]


@pytest.mark.asyncio
async def test_restriced_default_resource_pool_access(
    test_client: SanicASGITestClient, admin_user_headers: Dict[str, str], valid_resource_pool_payload: Dict[str, Any]
):
    valid_resource_pool_payload["default"] = True
    valid_resource_pool_payload["public"] = True
    del valid_resource_pool_payload["quota"]
    # Create default resource pool
    _, res = await create_rp(valid_resource_pool_payload, test_client)
    assert res.status_code == 201
    rp_default = res.json
    # Create a public non-default resource pool
    valid_resource_pool_payload["default"] = False
    _, res = await create_rp(valid_resource_pool_payload, test_client)
    assert res.status_code == 201
    rp_public = res.json
    # Create a user that has no acccess to the default pool
    no_default_user_id = "keycloak-id-1"
    user_payload = {"id": no_default_user_id, "no_default_access": True}
    _, res = await test_client.post("/api/data/users", headers=admin_user_headers, data=json.dumps(user_payload))
    assert res.status_code == 201
    no_default_access_token = json.dumps({"id": no_default_user_id})
    # Create a user that has access to the default pool
    user_id = "keycloak-id-2"
    user_payload = {"id": user_id, "no_default_access": False}
    _, res = await test_client.post("/api/data/users", headers=admin_user_headers, data=json.dumps(user_payload))
    access_token = json.dumps({"id": user_id})
    assert res.status_code == 201
    # Ensure non-authenticated users have acess to the default pool
    _, res = await test_client.get(f"/api/data/resource_pools/{rp_default['id']}")
    assert res.status_code == 200
    assert res.json == rp_default
    # Ensure non-authenticated users have acess to the public pool
    _, res = await test_client.get(f"/api/data/resource_pools/{rp_public['id']}")
    assert res.status_code == 200
    assert res.json == rp_public
    # Ensure that no_default_pool user cannot get the default pool
    _, res = await test_client.get(
        f"/api/data/resource_pools/{rp_default['id']}", headers={"Authorization": f"Bearer {no_default_access_token}"}
    )
    assert res.status_code == 404
    # Ensure that admin user can see the default pool
    _, res = await test_client.get(f"/api/data/resource_pools/{rp_default['id']}", headers=admin_user_headers)
    assert res.status_code == 200
    assert res.json == rp_default
    # Ensure that regular user can see the default pool
    _, res = await test_client.get(
        f"/api/data/resource_pools/{rp_default['id']}", headers={"Authorization": f"Bearer {access_token}"}
    )
    assert res.status_code == 200
    assert res.json == rp_default
    # Ensure that regular user can see the public pool
    _, res = await test_client.get(
        f"/api/data/resource_pools/{rp_public['id']}", headers={"Authorization": f"Bearer {access_token}"}
    )
    assert res.status_code == 200
    assert res.json == rp_public
    # Ensure that no_default user can see the public pool
    _, res = await test_client.get(
        f"/api/data/resource_pools/{rp_public['id']}", headers={"Authorization": f"Bearer {no_default_access_token}"}
    )
    assert res.status_code == 200
    assert res.json == rp_public


@pytest.mark.asyncio
async def test_private_resource_pool_access(
    test_client: SanicASGITestClient, admin_user_headers: Dict[str, str], valid_resource_pool_payload: Dict[str, Any]
):
    valid_resource_pool_payload["default"] = False
    valid_resource_pool_payload["public"] = False
    # Create private resource pool
    _, res = await create_rp(valid_resource_pool_payload, test_client)
    assert res.status_code == 201
    rp_private = res.json
    # Create a user that has no acccess to the private pool
    restricted_user_id = "keycloak-id-1"
    user_payload = {"id": restricted_user_id, "no_default_access": True}
    _, res = await test_client.post("/api/data/users", headers=admin_user_headers, data=json.dumps(user_payload))
    assert res.status_code == 201
    restricted_access_token = json.dumps({"id": restricted_user_id})
    # Create a user that has access to the private pool
    allowed_user_id = "keycloak-id-2"
    user_payload = {"id": allowed_user_id, "no_default_access": False}
    _, res = await test_client.post("/api/data/users", headers=admin_user_headers, data=json.dumps(user_payload))
    allowed_access_token = json.dumps({"id": allowed_user_id})
    _, res = await test_client.post(
        f"/api/data/users/{allowed_user_id}/resource_pools",
        headers=admin_user_headers,
        data=json.dumps([rp_private["id"]]),
    )
    assert res.status_code == 200
    # Ensure non-authenticated users cannot see the private pool
    _, res = await test_client.get(f"/api/data/resource_pools/{rp_private['id']}")
    assert res.status_code == 404
    # Ensure that a user that is not part of the private pool cannot see the pool
    _, res = await test_client.get(
        f"/api/data/resource_pools/{rp_private['id']}", headers={"Authorization": f"Bearer {restricted_access_token}"}
    )
    assert res.status_code == 404
    # Ensure that admin user can see the private pool
    _, res = await test_client.get(f"/api/data/resource_pools/{rp_private['id']}", headers=admin_user_headers)
    assert res.status_code == 200
    assert res.json == rp_private
    # Ensure that the user who is part of the private pool can see the pool
    _, res = await test_client.get(
        f"/api/data/resource_pools/{rp_private['id']}", headers={"Authorization": f"Bearer {allowed_access_token}"}
    )
    assert res.status_code == 200
    assert res.json == rp_private


@pytest.mark.asyncio
async def test_patch_tolerations(
    test_client: SanicASGITestClient, admin_user_headers: Dict[str, str], valid_resource_pool_payload: Dict[str, Any]
):
    valid_resource_pool_payload["classes"][0]["tolerations"] = ["toleration1"]
    _, res = await create_rp(valid_resource_pool_payload, test_client)
    assert res.status_code == 201
    rp = res.json
    rp_id = rp["id"]
    assert len(rp["classes"]) > 0
    res_class = rp["classes"][0]
    res_class_id = res_class["id"]
    assert len(res_class["tolerations"]) == 1
    # Patch in a 2nd toleration
    _, res = await test_client.patch(
        f"/api/data/resource_pools/{rp_id}/classes/{res_class_id}",
        headers=admin_user_headers,
        data=json.dumps({"tolerations": ["toleration2"]}),
    )
    assert res.status_code == 200
    assert "toleration2" in res.json["tolerations"]
    # Adding the same toleration again does not add copies of it
    _, res = await test_client.patch(
        f"/api/data/resource_pools/{rp_id}/classes/{res_class_id}",
        headers=admin_user_headers,
        data=json.dumps({"tolerations": ["toleration1"]}),
    )
    assert res.status_code == 200
    assert len(res.json["tolerations"]) == 2
    # Get the resource class to make sure that toleration is truly in the DB
    _, res = await test_client.get(
        f"/api/data/resource_pools/{rp_id}/classes/{res_class_id}",
        headers=admin_user_headers,
    )
    assert res.status_code == 200
    assert "toleration2" in res.json["tolerations"]
    assert "toleration1" in res.json["tolerations"]
    assert len(res.json["tolerations"]) == 2


@pytest.mark.asyncio
async def test_patch_affinities(
    test_client: SanicASGITestClient, admin_user_headers: Dict[str, str], valid_resource_pool_payload: Dict[str, Any]
):
    valid_resource_pool_payload["classes"][0]["node_affinities"] = [{"key": "affinity1"}]
    _, res = await create_rp(valid_resource_pool_payload, test_client)
    assert res.status_code == 201
    rp = res.json
    rp_id = rp["id"]
    assert len(rp["classes"]) > 0
    res_class = rp["classes"][0]
    res_class_id = res_class["id"]
    assert len(res_class["node_affinities"]) == 1
    assert res_class["node_affinities"][0] == {"key": "affinity1", "required_during_scheduling": False}
    # Patch in a 2nd affinity
    new_affinity = {"key": "affinity2"}
    _, res = await test_client.patch(
        f"/api/data/resource_pools/{rp_id}/classes/{res_class_id}",
        headers=admin_user_headers,
        data=json.dumps({"node_affinities": [new_affinity]}),
    )
    assert res.status_code == 200
    assert len(res.json["node_affinities"]) == 2
    inserted_affinity = next(filter(lambda x: x["key"] == new_affinity["key"], res.json["node_affinities"]))
    assert inserted_affinity["key"] == new_affinity["key"]
    assert not inserted_affinity["required_during_scheduling"]
    # Adding the same affinity again does not add copies of it
    _, res = await test_client.patch(
        f"/api/data/resource_pools/{rp_id}/classes/{res_class_id}",
        headers=admin_user_headers,
        data=json.dumps({"node_affinities": [new_affinity]}),
    )
    assert res.status_code == 200
    assert len(res.json["node_affinities"]) == 2
    # Updating an affinitiy required_during_scheduling field
    new_affinity = {"key": "affinity2", "required_during_scheduling": True}
    _, res = await test_client.patch(
        f"/api/data/resource_pools/{rp_id}/classes/{res_class_id}",
        headers=admin_user_headers,
        data=json.dumps({"node_affinities": [new_affinity]}),
    )
    assert res.status_code == 200
    assert len(res.json["node_affinities"]) == 2
    inserted_affinity = next(filter(lambda x: x["key"] == new_affinity["key"], res.json["node_affinities"]))
    assert inserted_affinity["required_during_scheduling"]
    # Get the resource class to make sure that node affinities are truly in the DB
    _, res = await test_client.get(
        f"/api/data/resource_pools/{rp_id}/classes/{res_class_id}",
        headers=admin_user_headers,
    )
    assert res.status_code == 200
    assert len(res.json["node_affinities"]) == 2
