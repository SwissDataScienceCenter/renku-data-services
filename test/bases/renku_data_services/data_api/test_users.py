import json
from uuid import uuid4

import pytest

from renku_data_services.users.models import UserInfo


@pytest.mark.asyncio
async def test_get_all_users_as_admin(sanic_client, users) -> None:
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
    _, res = await sanic_client.get(
        "/api/data/users",
        headers={"Authorization": f"bearer {json.dumps(admin_token)}"},
    )
    users.append(admin)
    assert res.status_code == 200, res.text
    assert len(res.json) == len(users)
    retrieved_users = [
        UserInfo(
            id=user["id"],
            first_name=user.get("first_name"),
            last_name=user.get("last_name"),
            email=user.get("email"),
        )
        for user in res.json
    ]
    assert set(retrieved_users) == set(users)
    for user in users:
        _, res = await sanic_client.get(
            f"/api/data/users/{user.id}",
            headers={"Authorization": f"bearer {json.dumps(admin_token)}"},
        )
        assert res.status_code == 200
        retrieved_user = UserInfo(
            id=res.json["id"],
            first_name=res.json.get("first_name"),
            last_name=res.json.get("last_name"),
            email=res.json.get("email"),
        )
        assert user == retrieved_user


@pytest.mark.asyncio
async def test_get_all_users_as_anonymous(sanic_client) -> None:
    _, res = await sanic_client.get("/api/data/users")
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_get_all_users_as_non_admin(sanic_client, users) -> None:
    user = users[0]
    access_token = {"id": user.id, "is_admin": False}
    _, res = await sanic_client.get(
        "/api/data/users",
        headers={"Authorization": f"bearer {json.dumps(access_token)}"},
    )
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_get_logged_in_user(sanic_client, users) -> None:
    user = users[0]
    access_token = {"id": user.id, "is_admin": False}
    _, res = await sanic_client.get(
        "/api/data/user",
        headers={"Authorization": f"bearer {json.dumps(access_token)}"},
    )
    assert res.status_code == 200
    retrieved_user = UserInfo(
        id=res.json["id"],
        first_name=res.json.get("first_name"),
        last_name=res.json.get("last_name"),
        email=res.json.get("email"),
    )
    assert retrieved_user == user
    _, res = await sanic_client.get(
        f"/api/data/users/{user.id}",
        headers={"Authorization": f"bearer {json.dumps(access_token)}"},
    )
    assert res.status_code == 200
    retrieved_user = UserInfo(
        id=res.json["id"],
        first_name=res.json.get("first_name"),
        last_name=res.json.get("last_name"),
        email=res.json.get("email"),
    )
    assert retrieved_user == user


@pytest.mark.asyncio
async def test_logged_in_users_can_get_other_users(sanic_client, users) -> None:
    user = users[0]
    other_user = users[1]
    access_token = {"id": user.id, "is_admin": False}
    _, res = await sanic_client.get(
        f"/api/data/users/{other_user.id}",
        headers={"Authorization": f"bearer {json.dumps(access_token)}"},
    )
    assert res.status_code == 200
    retrieved_other_user = UserInfo(
        id=res.json["id"],
        first_name=res.json.get("first_name"),
        last_name=res.json.get("last_name"),
        email=res.json.get("email"),
    )
    assert retrieved_other_user == other_user


@pytest.mark.asyncio
async def test_logged_in_user_check_adds_user_if_missing(sanic_client, users, admin_headers) -> None:
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
    _, res = await sanic_client.get(
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
    _, res = await sanic_client.get(
        "/api/data/users",
        headers=admin_headers,
    )
    assert res.status_code == 200
    users_response = [
        UserInfo(
            id=iuser["id"],
            first_name=iuser.get("first_name"),
            last_name=iuser.get("last_name"),
            email=iuser.get("email"),
        )
        for iuser in res.json
    ]
    assert user in users_response
