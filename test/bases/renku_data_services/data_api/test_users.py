import json
from uuid import uuid4

import pytest
from ulid import ULID

from renku_data_services.base_models.core import NamespacePath
from renku_data_services.namespace.models import UserNamespace
from renku_data_services.users.models import UserInfo


@pytest.mark.asyncio
async def test_get_all_users_as_admin(sanic_client, users) -> None:
    admin = UserInfo(
        id="admin-id",
        first_name="Admin",
        last_name="Adminson",
        email="admin@gmail.com",
        namespace=UserNamespace(
            id=ULID(),
            underlying_resource_id="admin-id",
            created_by="admin-id",
            path=NamespacePath.from_strings("admin.adminson"),
        ),
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
        (
            user["id"],
            user.get("first_name"),
            user.get("last_name"),
            user.get("email"),
        )
        for user in res.json
    ]
    existing_users = [
        (
            user.id,
            user.first_name,
            user.last_name,
            user.email,
        )
        for user in users
    ]
    assert set(retrieved_users) == set(existing_users)
    for user in users:
        _, res = await sanic_client.get(
            f"/api/data/users/{user.id}",
            headers={"Authorization": f"bearer {json.dumps(admin_token)}"},
        )
        assert res.status_code == 200
        retrieved_user = dict(
            id=res.json["id"],
            first_name=res.json.get("first_name"),
            last_name=res.json.get("last_name"),
            email=res.json.get("email"),
        )
        existing_user = dict(id=user.id, first_name=user.first_name, last_name=user.last_name, email=user.email)
        assert existing_user == retrieved_user


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
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_get_logged_in_user(sanic_client, users) -> None:
    user = users[0]
    user_dict = dict(id=user.id, first_name=user.first_name, last_name=user.last_name, email=user.email)
    access_token = {"id": user.id, "is_admin": False}
    _, res = await sanic_client.get(
        "/api/data/user",
        headers={"Authorization": f"bearer {json.dumps(access_token)}"},
    )
    assert res.status_code == 200
    retrieved_user = dict(
        id=res.json["id"],
        first_name=res.json.get("first_name"),
        last_name=res.json.get("last_name"),
        email=res.json.get("email"),
    )
    assert retrieved_user == user_dict
    _, res = await sanic_client.get(
        f"/api/data/users/{user.id}",
        headers={"Authorization": f"bearer {json.dumps(access_token)}"},
    )
    assert res.status_code == 200
    retrieved_user = dict(
        id=res.json["id"],
        first_name=res.json.get("first_name"),
        last_name=res.json.get("last_name"),
        email=res.json.get("email"),
    )
    assert retrieved_user == user_dict


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
    other_user = dict(
        id=other_user.id, first_name=other_user.first_name, last_name=other_user.last_name, email=other_user.email
    )
    retrieved_other_user = dict(
        id=res.json["id"],
        first_name=res.json.get("first_name"),
        last_name=res.json.get("last_name"),
        email=res.json.get("email"),
    )
    assert retrieved_other_user == other_user


@pytest.mark.asyncio
async def test_anonymous_users_can_get_other_users(sanic_client, users) -> None:
    other_user = users[1]
    _, res = await sanic_client.get(f"/api/data/users/{other_user.id}")
    assert res.status_code == 200
    other_user = dict(
        id=other_user.id, first_name=other_user.first_name, last_name=other_user.last_name, email=other_user.email
    )
    retrieved_other_user = dict(
        id=res.json["id"],
        first_name=res.json.get("first_name"),
        last_name=res.json.get("last_name"),
        email=res.json.get("email"),
    )
    assert retrieved_other_user == other_user


@pytest.mark.asyncio
async def test_logged_in_user_check_adds_user_if_missing(sanic_client, users, admin_headers) -> None:
    user_id = str(uuid4())
    user = dict(
        id=user_id,
        first_name="Peter",
        last_name="Parker",
        email="peter@spiderman.com",
    )
    access_token = {
        "id": user_id,
        "is_admin": False,
        "first_name": user["first_name"],
        "last_name": user["last_name"],
        "email": user["email"],
        "name": f"{user['first_name']} {user['last_name']}",
    }
    # Just by hitting the users endpoint with valid credentials the user will be aded to the database
    _, res = await sanic_client.get(
        f"/api/data/users/{user_id}",
        headers={"Authorization": f"bearer {json.dumps(access_token)}"},
    )
    assert res.status_code == 200
    user_response = dict(
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
        dict(
            id=iuser["id"],
            first_name=iuser.get("first_name"),
            last_name=iuser.get("last_name"),
            email=iuser.get("email"),
        )
        for iuser in res.json
    ]
    assert user in users_response


@pytest.mark.asyncio
async def test_delete_user(sanic_client, admin_headers) -> None:
    # Create a user
    user_id = str(uuid4())
    user = dict(
        id=user_id,
        first_name="Peter",
        last_name="Parker",
        email="peter@spiderman.com",
    )
    access_token = {
        "id": user_id,
        "is_admin": False,
        "first_name": user["first_name"],
        "last_name": user["last_name"],
        "email": user["email"],
        "name": f"{user['first_name']} {user['last_name']}",
    }
    # Just by hitting the users endpoint with valid credentials the user will be added to the database
    _, res = await sanic_client.get(
        f"/api/data/users/{user_id}",
        headers={"Authorization": f"bearer {json.dumps(access_token)}"},
    )

    # Check that the user just added via acccess token is returned in the list when the admin lists all users
    _, res = await sanic_client.get(
        "/api/data/users",
        headers=admin_headers,
    )
    assert res.status_code == 200
    users_response = [
        dict(
            id=iuser["id"],
            first_name=iuser.get("first_name"),
            last_name=iuser.get("last_name"),
            email=iuser.get("email"),
        )
        for iuser in res.json
    ]
    assert user in users_response

    # Delete a user
    _, res = await sanic_client.delete(
        f"/api/data/users/{user_id}",
        headers=admin_headers,
    )

    assert res.status_code == 204, res.text

    # Check that the user just added via acccess token is now not returned in the list when the admin lists all users
    _, res = await sanic_client.get(
        "/api/data/users",
        headers=admin_headers,
    )
    assert res.status_code == 200
    users_response = [
        dict(
            id=iuser["id"],
            first_name=iuser.get("first_name"),
            last_name=iuser.get("last_name"),
            email=iuser.get("email"),
        )
        for iuser in res.json
    ]
    assert user not in users_response


@pytest.mark.asyncio
async def test_get_self_user(sanic_client, user_headers, regular_user) -> None:
    _, response = await sanic_client.get("/api/data/user", headers=user_headers)

    assert response.status_code == 200, response.text
    assert response.json is not None
    user_info = response.json
    assert user_info.get("id") == regular_user.id
    assert user_info.get("username") == regular_user.namespace.path.serialize()
    assert user_info.get("email") == regular_user.email
    assert user_info.get("first_name") == regular_user.first_name
    assert user_info.get("last_name") == regular_user.last_name
    assert user_info.get("is_admin") is False


@pytest.mark.asyncio
async def test_get_self_user_as_admin(sanic_client, admin_headers, admin_user) -> None:
    _, response = await sanic_client.get("/api/data/user", headers=admin_headers)

    assert response.status_code == 200, response.text
    assert response.json is not None
    user_info = response.json
    assert user_info.get("id") == admin_user.id
    assert user_info.get("username") == admin_user.namespace.path.serialize()
    assert user_info.get("email") == admin_user.email
    assert user_info.get("first_name") == admin_user.first_name
    assert user_info.get("last_name") == admin_user.last_name
    assert user_info.get("is_admin") is True


@pytest.mark.asyncio
async def test_get_self_user_unauthenticated(sanic_client) -> None:
    _, response = await sanic_client.get("/api/data/user")

    assert response.status_code == 401, response.text
