from copy import deepcopy

import pytest
from sanic_testing.testing import SanicASGITestClient

from test.bases.renku_data_services.data_api.utils import create_rp
from test.utils import KindCluster

resource_pool_payload = {
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
}


async def create_resource_pool(sanic_client: SanicASGITestClient) -> int:
    payload = deepcopy(resource_pool_payload)
    _, res = await create_rp(payload, sanic_client)
    assert res.status_code == 201, res.text
    assert res.json is not None
    return res.json["id"]


@pytest.mark.asyncio
@pytest.mark.xdist_group("sessions")  # Needs to run on the same worker as the rest of the sessions tests
async def test_resource_usage_for_user(
    sanic_client: SanicASGITestClient,
    cluster: KindCluster,
) -> None:
    rp_id = await create_resource_pool(sanic_client)
    _, res = await sanic_client.get(
        f"/api/data/resource_pools/{rp_id}/usage",
        headers={"Authorization": 'Bearer {"is_admin": false}'},
    )

    assert "total_usage" in res.json
    assert "user_usage" in res.json


@pytest.mark.asyncio
@pytest.mark.xdist_group("sessions")  # Needs to run on the same worker as the rest of the sessions tests
async def test_resource_usage_for_admin(
    sanic_client: SanicASGITestClient,
    cluster: KindCluster,
) -> None:
    rp_id = await create_resource_pool(sanic_client)
    _, res = await sanic_client.get(
        f"/api/data/resource_pools/{rp_id}/usage?user_id=123",
        headers={"Authorization": 'Bearer {"id": "id2", "is_admin": false}'},
    )

    assert res.status_code == 403, res.text

    _, res = await sanic_client.get(
        f"/api/data/resource_pools/{rp_id}/usage?user_id=123",
        headers={"Authorization": '{"id": "id1", "is_admin": true}'},
    )

    assert res.status_code == 200, res.text
