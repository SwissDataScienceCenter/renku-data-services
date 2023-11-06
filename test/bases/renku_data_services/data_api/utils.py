import json
from typing import Any, Dict, Tuple

from sanic import Request
from sanic_testing.testing import SanicASGITestClient, TestingResponse


async def create_rp(payload: Dict[str, Any], test_client: SanicASGITestClient) -> Tuple[Request, TestingResponse]:
    return await test_client.post(
        "/api/data/resource_pools",
        headers={"Authorization": "bearer test"},
        data=json.dumps(payload),
    )


async def create_user_preferences(
    test_client: SanicASGITestClient, valid_add_pinned_project_payload: Dict[str, Any]
) -> Tuple[Request, TestingResponse]:
    """Create user preferencers by adding a pinned project"""
    return await test_client.post(
        "/api/data/user_preferences/pinned_projects",
        headers={"Authorization": "bearer test"},
        data=json.dumps(valid_add_pinned_project_payload),
    )
