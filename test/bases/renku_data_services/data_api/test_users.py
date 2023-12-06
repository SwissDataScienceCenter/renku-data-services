import json
from test.bases.renku_data_services.keycloak_sync.test_sync import get_kc_users
from typing import List

import pytest
import pytest_asyncio
from sanic import Sanic
from sanic_testing.testing import SanicASGITestClient

from renku_data_services.app_config import Config as DataConfig
from renku_data_services.data_api.app import register_all_handlers
from renku_data_services.users.dummy_kc_api import DummyKeycloakAPI
from renku_data_services.users.models import UserInfo


@pytest.fixture
def users() -> List[UserInfo]:
    return [
        UserInfo("user-1-id", "John", "Doe", "john.doe@gmail.com"),
        UserInfo("user-2-id", "Jane", "Doe", "jane.doe@gmail.com"),
    ]


@pytest_asyncio.fixture
async def users_test_client(app_config: DataConfig, users: List[UserInfo]) -> SanicASGITestClient:
    app_config.kc_api = DummyKeycloakAPI(users=get_kc_users(users))
    app = Sanic(app_config.app_name)
    app = register_all_handlers(app, app_config)
    await app_config.kc_user_repo.initialize(app_config.kc_api)
    return SanicASGITestClient(app)


@pytest.mark.asyncio
async def test_get_all_users_as_admin(users_test_client, users):
    admin_token = {"id": "admin-id", "is_admin": True}
    _, res = await users_test_client.get(
        "/api/data/users",
        headers={"Authorization": f"bearer {json.dumps(admin_token)}"},
    )
    assert res.status_code == 200
    assert len(res.json) == 2
    retrieved_users = [
        UserInfo(user["id"], user.get("first_name"), user.get("last_name"), user.get("email")) for user in res.json
    ]
    assert set(retrieved_users) == set(users)
    for user in users:
        _, res = await users_test_client.get(
            f"/api/data/users/{user.id}",
            headers={"Authorization": f"bearer {json.dumps(admin_token)}"},
        )
        assert res.status_code == 200
        retrieved_user = UserInfo(
            res.json["id"], res.json.get("first_name"), res.json.get("last_name"), res.json.get("email")
        )
        assert user == retrieved_user


@pytest.mark.asyncio
async def test_get_all_users_as_anonymous(users_test_client):
    _, res = await users_test_client.get("/api/data/users")
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_get_all_users_as_non_admin(users_test_client, users):
    user = users[0]
    access_token = {"id": user.id, "is_admin": False}
    _, res = await users_test_client.get(
        "/api/data/users",
        headers={"Authorization": f"bearer {json.dumps(access_token)}"},
    )
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_get_logged_in_user(users_test_client, users):
    user = users[0]
    access_token = {"id": user.id, "is_admin": False}
    _, res = await users_test_client.get(
        "/api/data/user",
        headers={"Authorization": f"bearer {json.dumps(access_token)}"},
    )
    assert res.status_code == 200
    retrieved_user = UserInfo(
        res.json["id"], res.json.get("first_name"), res.json.get("last_name"), res.json.get("email")
    )
    assert retrieved_user == user
    _, res = await users_test_client.get(
        f"/api/data/users/{user.id}",
        headers={"Authorization": f"bearer {json.dumps(access_token)}"},
    )
    assert res.status_code == 200
    retrieved_user = UserInfo(
        res.json["id"], res.json.get("first_name"), res.json.get("last_name"), res.json.get("email")
    )
    assert retrieved_user == user


@pytest.mark.asyncio
async def test_logged_in_users_cannot_get_other_users(users_test_client, users):
    user = users[0]
    other_user = users[1]
    access_token = {"id": user.id, "is_admin": False}
    _, res = await users_test_client.get(
        f"/api/data/users/{other_user.id}",
        headers={"Authorization": f"bearer {json.dumps(access_token)}"},
    )
    assert res.status_code == 401
