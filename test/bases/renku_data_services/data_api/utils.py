import json
from typing import Any

from sanic import Request
from sanic_testing.testing import SanicASGITestClient, TestingResponse

from renku_data_services.base_models import APIUser


class AttributeDictionary(dict):
    """Enables accessing dictionary keys as attributes"""

    def __init__(self, dictionary):
        for key, value in dictionary.items():
            # TODO check if key is a valid identifier
            if key == "list":
                raise ValueError("'list' is not allowed as a key")
            if isinstance(value, dict):
                value = AttributeDictionary(value)
            elif isinstance(value, list):
                value = [AttributeDictionary(v) if isinstance(v, dict) else v for v in value]
            self.__setattr__(key, value)
            self[key] = value

    def list(self):
        [value for _, value in self.items()]

    def __setitem__(self, k, v):
        if k == "list":
            raise ValueError("'list' is not allowed as a key")
        self.__setattr__(k, v)
        return super().__setitem__(k, v)


async def create_rp(payload: dict[str, Any], test_client: SanicASGITestClient) -> tuple[Request, TestingResponse]:
    return await test_client.post(
        "/api/data/resource_pools",
        headers={"Authorization": 'Bearer {"is_admin": true}'},
        data=json.dumps(payload),
    )


async def create_user_preferences(
    test_client: SanicASGITestClient, valid_add_pinned_project_payload: dict[str, Any], api_user: APIUser
) -> tuple[Request, TestingResponse]:
    """Create user preferences by adding a pinned project"""
    return await test_client.post(
        "/api/data/user/preferences/pinned_projects",
        headers={"Authorization": f"bearer {api_user.access_token}"},
        data=json.dumps(valid_add_pinned_project_payload),
    )


def merge_headers(*headers: dict[str, str]) -> dict[str, str]:
    """Merge multiple headers."""
    all_headers = dict()
    for h in headers:
        all_headers.update(**h)
    return all_headers
