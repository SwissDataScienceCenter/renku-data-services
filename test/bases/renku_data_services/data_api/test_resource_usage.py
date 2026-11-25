from copy import deepcopy

import pytest
from sanic_testing.testing import SanicASGITestClient

from renku_data_services.resource_usage.model import Credit
from test.bases.renku_data_services.data_api.utils import create_rp
from test.components.renku_data_services.resource_usage.helper import FakeMetering
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
            "quota_enforced": True,
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
@pytest.mark.parametrize(
    "headers,expected_status",
    [
        ({}, 401),
        ({"Authorization": 'Bearer {"id": "id2", "is_admin": false}'}, 403),
    ],
)
async def test_resource_usage_requires_admin(
    sanic_client: SanicASGITestClient,
    cluster: KindCluster,
    fake_metering: FakeMetering,
    headers: dict[str, str],
    expected_status: int,
) -> None:
    rp_id = await create_resource_pool(sanic_client)

    _, res = await sanic_client.get(f"/api/data/resource_pools/{rp_id}/usage?user_id=123", headers=headers)

    assert res.status_code == expected_status, res.text


@pytest.mark.asyncio
@pytest.mark.xdist_group("sessions")  # Needs to run on the same worker as the rest of the sessions tests
async def test_resource_usage_without_metering(
    sanic_client: SanicASGITestClient,
    admin_headers: dict[str, str],
    cluster: KindCluster,
) -> None:
    rp_id = await create_resource_pool(sanic_client)

    _, res = await sanic_client.get(f"/api/data/resource_pools/{rp_id}/usage", headers=admin_headers)

    assert res.status_code == 404, res.text


@pytest.mark.asyncio
@pytest.mark.xdist_group("sessions")  # Needs to run on the same worker as the rest of the sessions tests
@pytest.mark.parametrize("user_id,expected_user_usage", [(None, None), ("user-1", 30), ("user-3", 0)])
async def test_resource_usage_for_admin(
    sanic_client: SanicASGITestClient,
    admin_headers: dict[str, str],
    cluster: KindCluster,
    fake_metering: FakeMetering,
    user_id: str | None,
    expected_user_usage: int | None,
) -> None:
    rp_id = await create_resource_pool(sanic_client)
    fake_metering.pool_limits[rp_id] = Credit.from_int(1000)
    fake_metering.add_usage(rp_id, "user-1", 30)
    fake_metering.add_usage(rp_id, "user-2", 20)

    url = f"/api/data/resource_pools/{rp_id}/usage"
    if user_id is not None:
        url += f"?user_id={user_id}"
    _, res = await sanic_client.get(url, headers=admin_headers)

    assert res.status_code == 200, res.text
    assert res.json["total_usage"] == 50
    assert res.json.get("user_usage") == expected_user_usage
    assert res.json["pool_limits"]["pool_id"] == rp_id
    assert res.json["pool_limits"]["total_limit"] == 1000
