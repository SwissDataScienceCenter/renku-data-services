import json
from dataclasses import asdict
from test.bases.renku_data_services.keycloak_sync.test_sync import get_kc_users
from typing import List
from uuid import uuid4

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
    admin = UserInfo(
        id="admin-id",
        first_name="Admin",
        last_name="Adminson",
        email="admin@gmail.com",
    )
    admin_token = {
        "id": admin.id,
        "is_admin": True,
        "first_name": admin.first_name,
        "last_name": admin.last_name,
        "email": admin.email,
    }
    _, res = await users_test_client.get(
        "/api/data/users",
        headers={"Authorization": f"bearer {json.dumps(admin_token)}"},
    )
    users.append(admin)
    assert res.status_code == 200
    assert len(res.json) == len(users)
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


@pytest.mark.asyncio
async def test_logged_in_user_check_adds_user_if_missing(users_test_client, users, admin_user):
    user = UserInfo(
        id=str(uuid4()),
        first_name="Peter",
        last_name="Parker",
        email="peter@spiderman.com",
    )
    # The user is not really in the database
    assert user not in users
    access_token = {
        "id": user.id,
        "is_admin": False,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "email": user.email,
        "name": f"{user.first_name} {user.last_name}",
    }
    # Just by hitting the users endpoint with valid credentials the user will be aded to the database
    _, res = await users_test_client.get(
        f"/api/data/users/{user.id}",
        headers={"Authorization": f"bearer {json.dumps(access_token)}"},
    )
    assert res.status_code == 200
    user_response = UserInfo(
        id=res.json["id"],
        first_name=res.json.get("first_name"),
        last_name=res.json.get("last_name"),
        email=res.json.get("email"),
    )
    assert user_response == user
    # Check that the user just added via acccess token is returned in the list when the admin lists all users
    admin_token = json.dumps(asdict(admin_user))
    _, res = await users_test_client.get(
        f"/api/data/users",
        headers={"Authorization": f"bearer {admin_token}"},
    )
    assert res.status_code == 200
    users_response = [UserInfo(**iuser) for iuser in res.json]
    assert user in users_response
