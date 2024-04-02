import json
from test.bases.renku_data_services.keycloak_sync.test_sync import get_kc_users
from typing import Dict, List

import pytest
import pytest_asyncio
from sanic import Sanic
from sanic_testing.testing import SanicASGITestClient

from renku_data_services.app_config import Config
from renku_data_services.data_api.app import register_all_handlers
from renku_data_services.users.dummy_kc_api import DummyKeycloakAPI
from renku_data_services.users.models import UserInfo


@pytest.fixture
def users() -> List[UserInfo]:
    return [
        UserInfo("admin", "Admin", "Doe", "admin.doe@gmail.com"),
        UserInfo("user", "User", "Doe", "user.doe@gmail.com"),
        UserInfo("member-1", "Member-1", "Doe", "member-1.doe@gmail.com"),
        UserInfo("member-2", "Member-2", "Doe", "member-2.doe@gmail.com"),
    ]


@pytest_asyncio.fixture
async def sanic_client(app_config: Config, users: List[UserInfo]) -> SanicASGITestClient:
    app_config.kc_api = DummyKeycloakAPI(users=get_kc_users(users))
    app = Sanic(app_config.app_name)
    app = register_all_handlers(app, app_config)
    await app_config.kc_user_repo.initialize(app_config.kc_api)
    await app_config.group_repo.generate_user_namespaces()
    return SanicASGITestClient(app)


@pytest.fixture
def admin_headers() -> Dict[str, str]:
    """Authentication headers for an admin user."""
    access_token = json.dumps({"is_admin": True, "id": "admin", "name": "Admin User"})
    return {"Authorization": f"Bearer {access_token}"}


@pytest.fixture
def user_headers() -> Dict[str, str]:
    """Authentication headers for a normal user."""
    access_token = json.dumps({"is_admin": False, "id": "user", "name": "Normal User"})
    return {"Authorization": f"Bearer {access_token}"}


@pytest.fixture
def unauthorized_headers() -> Dict[str, str]:
    """Authentication headers for an anonymous user (did not log in)."""
    return {"Authorization": "Bearer {}"}


@pytest.mark.asyncio
async def test_list_namespaces(sanic_client, user_headers):
    payload = {
        "name": "Group1",
        "slug": "group-1",
        "description": "Group 1 Description",
    }
    _, response = await sanic_client.post("/api/data/groups", headers=user_headers, json=payload)
    assert response.status_code == 201, response.text
    _, response = await sanic_client.get("/api/data/namespaces", headers=user_headers)
    assert response.status_code == 200, response.text
    res_json = response.json
    assert len(res_json) == 2
    user_ns = res_json[0]
    assert user_ns["slug"] == "user.doe"
    group_ns = res_json[1]
    assert group_ns["slug"] == "group-1"


@pytest.mark.asyncio
async def test_get_namespace_by_slug(sanic_client, user_headers):
    payload = {
        "name": "Group1",
        "slug": "group-1",
        "description": "Group 1 Description",
    }
    _, response = await sanic_client.post("/api/data/groups", headers=user_headers, json=payload)
    assert response.status_code == 201, response.text
    _, response = await sanic_client.get(f"/api/data/namespaces/{payload['slug']}", headers=user_headers)
    assert response.status_code == 200, response.text
    assert response.json["slug"] == payload["slug"]
    assert response.json["namespace_kind"] == "group"
    _, response = await sanic_client.get("/api/data/namespaces/user.doe", headers=user_headers)
    assert response.status_code == 200, response.text
    assert response.json["slug"] == "user.doe"
    assert response.json["namespace_kind"] == "user"
