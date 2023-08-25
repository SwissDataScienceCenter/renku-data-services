import json
from test.bases.renku_data_services.crc_api.utils import create_rp
from typing import Any, Dict

import pytest
from sanic import Sanic
from sanic_testing.testing import SanicASGITestClient

from renku_data_services.crc_api.app import register_all_handlers
from renku_data_services.crc_api.config import Config
from renku_data_services.k8s.clients import DummyCoreClient, DummySchedulingClient
from renku_data_services.k8s.quota import QuotaRepository
from renku_data_services.resource_pool_adapters import ResourcePoolRepository, UserRepository
from renku_data_services.users.dummy import DummyAuthenticator, DummyUserStore

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
def test_client(pool_repo: ResourcePoolRepository, user_repo: UserRepository) -> SanicASGITestClient:
    config = Config(
        rp_repo=pool_repo,
        user_repo=user_repo,
        user_store=DummyUserStore(),
        authenticator=DummyAuthenticator(admin=True),
        quota_repo=QuotaRepository(DummyCoreClient({}), DummySchedulingClient({})),
    )

    app = Sanic(config.app_name)
    app = register_all_handlers(app, config)
    return SanicASGITestClient(app)


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
async def test_get_single_pool_quota(test_client: SanicASGITestClient, valid_resource_pool_payload: Dict[str, Any]):
    _, res = await create_rp(valid_resource_pool_payload, test_client)
    assert res.status_code == 201
    _, res = await test_client.get(
        "/api/data/resource_pools/1",
        headers={"Authorization": "bearer test"},
    )
    assert res.status_code == 200
    assert res.json.get("name") == "test-name"
    _, res = await test_client.get(
        "/api/data/resource_pools/1/quota",
        headers={"Authorization": "bearer test"},
    )
    assert res.status_code == 200
    assert res.json.get("cpu") == 100.0
    assert res.json.get("memory") == 100
    assert res.json.get("gpu") == 0
    assert res.json.get("id") is not None


@pytest.mark.asyncio
async def test_patch_quota(test_client: SanicASGITestClient, valid_resource_pool_payload: Dict[str, Any]):
    _, res = await create_rp(valid_resource_pool_payload, test_client)
    assert res.status_code == 201
    _, res = await test_client.patch(
        "/api/data/resource_pools/1/quota", headers={"Authorization": "bearer test"}, data=json.dumps({"cpu": 1000})
    )
    assert res.status_code == 200
    assert res.json.get("cpu") == 1000


@pytest.mark.asyncio
async def test_put_quota(test_client: SanicASGITestClient, valid_resource_pool_payload: Dict[str, Any]):
    _, res = await create_rp(valid_resource_pool_payload, test_client)
    assert res.status_code == 201
    _, res = await test_client.get(
        "/api/data/resource_pools/1/quota",
        headers={"Authorization": "bearer test"},
    )
    assert res.status_code == 200
    quota = res.json
    quota = {**quota, "cpu": 1000, "memory": 1000, "gpu": 1000}
    _, res = await test_client.put(
        "/api/data/resource_pools/1/quota", headers={"Authorization": "bearer test"}, data=json.dumps(quota)
    )
    assert res.status_code == 200
    assert res.json == quota


@pytest.mark.asyncio
async def test_patch_resource_class(test_client: SanicASGITestClient, valid_resource_pool_payload: Dict[str, Any]):
    _, res = await create_rp(valid_resource_pool_payload, test_client)
    assert res.status_code == 201
    _, res = await test_client.patch(
        "/api/data/resource_pools/1/classes/1", headers={"Authorization": "bearer test"}, data=json.dumps({"cpu": 5.0})
    )
    assert res.status_code == 200
    assert res.json.get("cpu") == 5.0


@pytest.mark.asyncio
async def test_put_resource_class(test_client: SanicASGITestClient, valid_resource_pool_payload: Dict[str, Any]):
    _, res = await create_rp(valid_resource_pool_payload, test_client)
    assert res.status_code == 201
    assert len(res.json.get("classes", [])) == 1
    res_cls_payload = {**res.json.get("classes", [])[0], "cpu": 5.0}
    res_cls_expected_response = {**res.json.get("classes", [])[0], "cpu": 5.0}
    res_cls_payload.pop("id", None)
    _, res = await test_client.put(
        "/api/data/resource_pools/1/classes/1",
        headers={"Authorization": "bearer test"},
        data=json.dumps(res_cls_payload),
    )
    assert res.status_code == 200
    assert res.json == res_cls_expected_response
