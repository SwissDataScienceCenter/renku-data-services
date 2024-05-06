import json
from copy import deepcopy
from test.bases.renku_data_services.data_api.utils import create_rp
from typing import Any

import pytest
from sanic_testing.testing import SanicASGITestClient

_valid_resource_pool_payload: dict[str, Any] = {
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
}


@pytest.fixture
def valid_resource_pool_payload() -> dict[str, Any]:
    return deepcopy(_valid_resource_pool_payload)


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
    sanic_client: SanicASGITestClient,
    payload: dict[str, Any],
    expected_status_code: int,
):
    _, res = await create_rp(payload, sanic_client)
    assert res.status_code == expected_status_code


@pytest.mark.asyncio
async def test_resource_pool_quotas(sanic_client: SanicASGITestClient):
    _, res = await create_rp(_valid_resource_pool_payload, sanic_client)
    assert res.status_code == 201

    assert res.json.get("idle_threshold") == 86400
    assert res.json.get("hibernation_threshold") == 99999


@pytest.mark.asyncio
async def test_resource_class_filtering(
    sanic_client: SanicASGITestClient,
    admin_headers: dict[str, str],
):
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
    payload = deepcopy(_valid_resource_pool_payload)
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
async def test_get_single_pool_quota(
    sanic_client: SanicASGITestClient, valid_resource_pool_payload: dict[str, Any], admin_headers: dict[str, str]
):
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
async def test_patch_quota(
    sanic_client: SanicASGITestClient, valid_resource_pool_payload: dict[str, Any], admin_headers: dict[str, str]
):
    _, res = await create_rp(valid_resource_pool_payload, sanic_client)
    assert res.status_code == 201
    _, res = await sanic_client.patch(
        "/api/data/resource_pools/1/quota", headers=admin_headers, data=json.dumps({"cpu": 1000})
    )
    assert res.status_code == 200
    assert res.json.get("cpu") == 1000


@pytest.mark.asyncio
async def test_put_quota(
    sanic_client: SanicASGITestClient, valid_resource_pool_payload: dict[str, Any], admin_headers: dict[str, str]
):
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
async def test_patch_resource_class(
    sanic_client: SanicASGITestClient, valid_resource_pool_payload: dict[str, Any], admin_headers: dict[str, str]
):
    _, res = await create_rp(valid_resource_pool_payload, sanic_client)
    assert res.status_code == 201
    _, res = await sanic_client.patch(
        "/api/data/resource_pools/1/classes/1", headers=admin_headers, data=json.dumps({"cpu": 5.0})
    )
    assert res.status_code == 200
    assert res.json.get("cpu") == 5.0


@pytest.mark.asyncio
async def test_put_resource_class(
    sanic_client: SanicASGITestClient, valid_resource_pool_payload: dict[str, Any], admin_headers: dict[str, str]
):
    _, res = await create_rp(valid_resource_pool_payload, sanic_client)
    assert res.status_code == 201
    assert len(res.json.get("classes", [])) == 1
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
async def test_restriced_default_resource_pool_access(
    sanic_client: SanicASGITestClient, admin_headers: dict[str, str], valid_resource_pool_payload: dict[str, Any]
):
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
    # Ensure non-authenticated users have acess to the default pool
    _, res = await sanic_client.get(f"/api/data/resource_pools/{rp_default['id']}")
    assert res.status_code == 200
    assert res.json == rp_default
    # Ensure non-authenticated users have acess to the public pool
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
async def test_restriced_default_resource_pool_access_changes(
    sanic_client: SanicASGITestClient, admin_headers: dict[str, str], valid_resource_pool_payload: dict[str, Any]
):
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
async def test_private_resource_pool_access(
    sanic_client: SanicASGITestClient, admin_headers: dict[str, str], valid_resource_pool_payload: dict[str, Any]
):
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
async def test_remove_resource_pool_users(
    sanic_client: SanicASGITestClient, admin_headers: dict[str, str], valid_resource_pool_payload: dict[str, Any]
):
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
async def test_user_resource_pools(
    sanic_client: SanicASGITestClient, admin_headers: dict[str, str], valid_resource_pool_payload: dict[str, Any]
):
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
    res.status_code == 201
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
    res.status_code == 200
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
async def test_patch_tolerations(
    sanic_client: SanicASGITestClient, admin_headers: dict[str, str], valid_resource_pool_payload: dict[str, Any]
):
    valid_resource_pool_payload["classes"][0]["tolerations"] = ["toleration1"]
    _, res = await create_rp(valid_resource_pool_payload, sanic_client)
    assert res.status_code == 201
    rp = res.json
    rp_id = rp["id"]
    assert len(rp["classes"]) > 0
    res_class = rp["classes"][0]
    res_class_id = res_class["id"]
    assert len(res_class["tolerations"]) == 1
    # Patch in a 2nd toleration
    _, res = await sanic_client.patch(
        f"/api/data/resource_pools/{rp_id}/classes/{res_class_id}",
        headers=admin_headers,
        data=json.dumps({"tolerations": ["toleration2"]}),
    )
    assert res.status_code == 200
    assert "toleration2" in res.json["tolerations"]
    # Adding the same toleration again does not add copies of it
    _, res = await sanic_client.patch(
        f"/api/data/resource_pools/{rp_id}/classes/{res_class_id}",
        headers=admin_headers,
        data=json.dumps({"tolerations": ["toleration1"]}),
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
async def test_patch_affinities(
    sanic_client: SanicASGITestClient, admin_headers: dict[str, str], valid_resource_pool_payload: dict[str, Any]
):
    valid_resource_pool_payload["classes"][0]["node_affinities"] = [{"key": "affinity1"}]
    _, res = await create_rp(valid_resource_pool_payload, sanic_client)
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
    _, res = await sanic_client.patch(
        f"/api/data/resource_pools/{rp_id}/classes/{res_class_id}",
        headers=admin_headers,
        data=json.dumps({"node_affinities": [new_affinity]}),
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
        data=json.dumps({"node_affinities": [new_affinity]}),
    )
    assert res.status_code == 200
    assert len(res.json["node_affinities"]) == 2
    # Updating an affinitiy required_during_scheduling field
    new_affinity = {"key": "affinity2", "required_during_scheduling": True}
    _, res = await sanic_client.patch(
        f"/api/data/resource_pools/{rp_id}/classes/{res_class_id}",
        headers=admin_headers,
        data=json.dumps({"node_affinities": [new_affinity]}),
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
async def test_remove_all_tolerations_put(
    sanic_client: SanicASGITestClient, admin_headers: dict[str, str], valid_resource_pool_payload: dict[str, Any]
):
    valid_resource_pool_payload["classes"][0]["tolerations"] = ["toleration1"]
    _, res = await create_rp(valid_resource_pool_payload, sanic_client)
    assert res.status_code == 201
    rp = res.json
    rp_id = rp["id"]
    assert len(rp["classes"]) > 0
    res_class = rp["classes"][0]
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
async def test_remove_all_affinities_put(
    sanic_client: SanicASGITestClient, admin_headers: dict[str, str], valid_resource_pool_payload: dict[str, Any]
):
    valid_resource_pool_payload["classes"][0]["node_affinities"] = [{"key": "affinity1"}]
    _, res = await create_rp(valid_resource_pool_payload, sanic_client)
    assert res.status_code == 201
    rp = res.json
    rp_id = rp["id"]
    assert len(rp["classes"]) > 0
    res_class = rp["classes"][0]
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
async def test_put_tolerations(
    sanic_client: SanicASGITestClient, admin_headers: dict[str, str], valid_resource_pool_payload: dict[str, Any]
):
    valid_resource_pool_payload["classes"][0]["tolerations"] = ["toleration1"]
    _, res = await create_rp(valid_resource_pool_payload, sanic_client)
    assert res.status_code == 201
    rp = res.json
    rp_id = rp["id"]
    assert len(rp["classes"]) > 0
    res_class = rp["classes"][0]
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
    assert res.status_code == 200
    assert res.json["tolerations"] == ["toleration2", "toleration3"]
    _, res = await sanic_client.get(
        f"/api/data/resource_pools/{rp_id}/classes/{res_class_id}",
        headers=admin_headers,
    )
    assert res.status_code == 200
    assert res.json["tolerations"] == ["toleration2", "toleration3"]


@pytest.mark.asyncio
async def test_put_affinities(
    sanic_client: SanicASGITestClient, admin_headers: dict[str, str], valid_resource_pool_payload: dict[str, Any]
):
    valid_resource_pool_payload["classes"][0]["node_affinities"] = [{"key": "affinity1"}]
    _, res = await create_rp(valid_resource_pool_payload, sanic_client)
    assert res.status_code == 201
    rp = res.json
    rp_id = rp["id"]
    assert len(rp["classes"]) > 0
    res_class = rp["classes"][0]
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
async def test_get_all_tolerations(
    sanic_client: SanicASGITestClient, admin_headers: dict[str, str], valid_resource_pool_payload: dict[str, Any]
):
    valid_resource_pool_payload["classes"][0]["tolerations"] = ["toleration1"]
    _, res = await create_rp(valid_resource_pool_payload, sanic_client)
    assert res.status_code == 201
    rp = res.json
    rp_id = rp["id"]
    assert len(rp["classes"]) > 0
    res_class = rp["classes"][0]
    res_class_id = res_class["id"]
    _, res = await sanic_client.get(
        f"/api/data/resource_pools/{rp_id}/classes/{res_class_id}/tolerations",
        headers=admin_headers,
    )
    assert res.status_code == 200
    assert res.json == ["toleration1"]


@pytest.mark.asyncio
async def test_get_all_affinities(
    sanic_client: SanicASGITestClient, admin_headers: dict[str, str], valid_resource_pool_payload: dict[str, Any]
):
    valid_resource_pool_payload["classes"][0]["node_affinities"] = [{"key": "affinity1"}]
    _, res = await create_rp(valid_resource_pool_payload, sanic_client)
    assert res.status_code == 201
    rp = res.json
    rp_id = rp["id"]
    assert len(rp["classes"]) > 0
    res_class = rp["classes"][0]
    res_class_id = res_class["id"]
    _, res = await sanic_client.get(
        f"/api/data/resource_pools/{rp_id}/classes/{res_class_id}/node_affinities",
        headers=admin_headers,
    )
    assert res.status_code == 200
    assert res.json == [{"key": "affinity1", "required_during_scheduling": False}]


@pytest.mark.asyncio
async def test_delete_all_affinities(
    sanic_client: SanicASGITestClient, admin_headers: dict[str, str], valid_resource_pool_payload: dict[str, Any]
):
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
async def test_delete_all_tolerations(
    sanic_client: SanicASGITestClient, admin_headers: dict[str, str], valid_resource_pool_payload: dict[str, Any]
):
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
