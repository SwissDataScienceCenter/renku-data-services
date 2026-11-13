"""The session clock route is reachable on the real data-api app."""

import json

from sanic_testing.testing import SanicASGITestClient

MISSING_ID = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
URL = f"/api/data/internal/sessions/{MISSING_ID}/interaction"


def _role_headers() -> dict[str, str]:
    token = json.dumps({"id": "service-account-ssh-proxy", "roles": ["ssh-proxy"], "is_admin": False})
    return {"Authorization": f"Bearer {token}"}


async def test_route_is_registered_and_role_gated(sanic_client: SanicASGITestClient, unauthorized_headers):
    _, response = await sanic_client.get(URL, headers=unauthorized_headers)
    assert response.status_code == 401

    _, response = await sanic_client.get(URL, headers=_role_headers())
    assert response.status_code == 404
