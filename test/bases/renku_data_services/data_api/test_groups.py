import json
from datetime import datetime
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
async def test_group_creation(sanic_client, user_headers):
    payload = {
        "name": "Group1",
        "slug": "group-1",
        "description": "Group 1 Description",
    }

    _, response = await sanic_client.post("/api/data/groups", headers=user_headers, json=payload)

    assert response.status_code == 201, response.text
    res_json = response.json
    assert res_json["name"] == payload["name"]
    assert res_json["slug"] == payload["slug"]
    assert res_json["description"] == payload["description"]
    assert res_json["created_by"] == "user"
    datetime.fromisoformat(res_json["creation_date"])

    _, response = await sanic_client.get("/api/data/groups", headers=user_headers)
    res_json = response.json
    print(response.text)
    assert response.status_code == 200
    assert len(res_json) == 1
    assert res_json[0]["name"] == payload["name"]


@pytest.mark.asyncio
async def test_group_pagination(sanic_client, user_headers):
    for i in range(15):
        payload = {"name": f"group{i}", "slug": f"group{i}"}
        _, response = await sanic_client.post("/api/data/groups", headers=user_headers, json=payload)
        assert response.status_code == 201
    _, res1 = await sanic_client.get("/api/data/groups", headers=user_headers, params={"per_page": 12, "page": 1})
    _, res2 = await sanic_client.get("/api/data/groups", headers=user_headers, params={"per_page": 12, "page": 2})
    assert res1.status_code == 200
    assert res2.status_code == 200
    res1_json = res1.json
    res2_json = res2.json
    assert len(res1_json) == 12
    assert len(res2_json) == 3
    assert res1_json[0]["name"] == "group0"
    assert res1_json[-1]["name"] == "group11"
    assert res2_json[0]["name"] == "group12"
    assert res2_json[-1]["name"] == "group14"


@pytest.mark.asyncio
async def test_group_patch_delete(sanic_client, user_headers):
    payload = {
        "name": "Group1",
        "slug": "group-1",
        "description": "Group 1 Description",
    }
    _, response = await sanic_client.post("/api/data/groups", headers=user_headers, json=payload)
    assert response.status_code == 201, response.text
    res_json = response.json
    assert res_json["name"] == payload["name"]
    assert res_json["slug"] == payload["slug"]
    assert res_json["description"] == payload["description"]
    new_payload = {
        "name": "Group2",
        "slug": "group-2",
        "description": "Group 2 Description",
    }
    _, response = await sanic_client.patch("/api/data/groups/group-1", headers=user_headers, json=new_payload)
    assert response.status_code == 200, response.text
    res_json = response.json
    assert res_json["name"] == new_payload["name"]
    assert res_json["slug"] == new_payload["slug"]
    assert res_json["description"] == new_payload["description"]
    _, response = await sanic_client.delete("/api/data/groups/group-1", headers=user_headers)
    assert response.status_code == 204
    _, response = await sanic_client.get("/api/data/groups/group-1", headers=user_headers)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_group_members(sanic_client, user_headers):
    payload = {
        "name": "Group1",
        "slug": "group-1",
        "description": "Group 1 Description",
    }
    _, response = await sanic_client.post("/api/data/groups", headers=user_headers, json=payload)
    assert response.status_code == 201, response.text
    _, response = await sanic_client.get("/api/data/groups/group-1/members", headers=user_headers)
    assert response.status_code == 200, response.text
    res_json = response.json
    assert len(res_json) == 1
    assert res_json[0]["id"] == "user"
    assert res_json[0]["role"] == "owner"
    new_members = [{"id": "member-1", "role": "member"}]
    _, response = await sanic_client.patch("/api/data/groups/group-1/members", headers=user_headers, json=new_members)
    assert response.status_code == 200
    _, response = await sanic_client.get("/api/data/groups/group-1/members", headers=user_headers)
    assert response.status_code == 200, response.text
    res_json = response.json
    assert len(res_json) == 2
    assert res_json[1]["id"] == "member-1"
    assert res_json[1]["role"] == "member"
