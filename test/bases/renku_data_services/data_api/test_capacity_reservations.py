import pytest
from sanic_testing.testing import SanicASGITestClient


@pytest.mark.asyncio
async def test_get_capacity_reservations_unauthorized(sanic_client: SanicASGITestClient) -> None:
    _, response = await sanic_client.get("/api/data/capacity-reservations")

    assert response.status_code == 401, response.text


@pytest.mark.asyncio
async def test_post_capacity_reservations_schemathesis_error(
    sanic_client: SanicASGITestClient, admin_headers: dict[str, str]
) -> None:
    payload = {
        "name": "",
        "provisioning": {
            "lead_time_minutes": 0,
            "placeholder_count": 1,
            "scale_down_behavior": "none",
        },
        "recurrence": {"end_date": "2000-01-01", "start_date": "2000-01-01", "type": "once"},
        "resource_class_id": 0,
        "project_template_id": "0",
    }

    _, response = await sanic_client.post("/api/data/capacity-reservations", headers=admin_headers, json=payload)

    assert response.status_code == 422, response.text
