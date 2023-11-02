import json
from typing import Any, Dict, Tuple

from sanic import Request
from sanic_testing.testing import SanicASGITestClient, TestingResponse


async def create_rp(payload: Dict[str, Any], test_client: SanicASGITestClient) -> Tuple[Request, TestingResponse]:
    return await test_client.post(
        "/api/data/resource_pools",
        headers={"Authorization": 'Bearer {"is_admin": true}'},
        data=json.dumps(payload),
    )
