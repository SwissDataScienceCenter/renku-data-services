import json
from typing import Any, Dict, Tuple

from sanic import Request
from sanic_testing.testing import SanicTestClient, TestingResponse


def create_rp(payload: Dict[str, Any], test_client: SanicTestClient) -> Tuple[Request, TestingResponse]:
    return test_client.post(
        "/api/data/resource_pools",
        headers={"Authorization": "bearer test"},
        data=json.dumps(payload),
    )
