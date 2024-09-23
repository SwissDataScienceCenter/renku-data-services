import json
from uuid import uuid4

import pytest
from ulid import ULID

from renku_data_services.namespace.models import Namespace, NamespaceKind
from renku_data_services.users.models import UserInfo


@pytest.mark.asyncio
async def test_get_all_users_as_admin(sanic_client, users) -> None:
    admin = UserInfo(
        id="admin-id",
        first_name="Admin",
        last_name="Adminson",
        email="admin@gmail.com",
        namespace=Namespace(
            id=ULID(),
            slug="admin.adminson",
            kind=NamespaceKind.user,
            underlying_resource_id="admin-id",
            created_by="admin-id",
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
        "name": f"{user["first_name"]} {user["last_name"]}",
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
async def test_delete_user(sanic_client, user_headers, app_config, users) -> None:
    # Create an admin user
    admin = UserInfo(
        id="admin-id",
        first_name="Admin",
        last_name="Adminson",
        email="admin@gmail.com",
        namespace=Namespace(
            id=ULID(),
            slug="admin.adminson",
            kind=NamespaceKind.user,
            underlying_resource_id="admin-id",
            created_by="admin-id",
        ),
    )
    admin_token = {
        "id": admin.id,
        "is_admin": True,
        "first_name": admin.first_name,
        "last_name": admin.last_name,
        "email": admin.email,
    }

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
        "name": f"{user["first_name"]} {user["last_name"]}",
    }
    # Just by hitting the users endpoint with valid credentials the user will be aded to the database
    _, res = await sanic_client.get(
        f"/api/data/users/{user_id}",
        headers={"Authorization": f"bearer {json.dumps(access_token)}"},
    )

    # Check that the user just added via acccess token is returned in the list when the admin lists all users
    _, res = await sanic_client.get(
        "/api/data/users",
        headers={"Authorization": f"bearer {json.dumps(admin_token)}"},
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
        headers={"Authorization": f"bearer {json.dumps(admin_token)}"},
    )

    assert res.status_code == 204, res.text

    # Check that the user just added via acccess token is now not returned in the list when the admin lists all users
    _, res = await sanic_client.get(
        "/api/data/users",
        headers={"Authorization": f"bearer {json.dumps(admin_token)}"},
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

    # Delete a project
    # project_id = project["id"]
    # _, response = await sanic_client.delete(f"/api/data/projects/{user_id}", headers=user_headers)

    # events = await app_config.event_repo._get_pending_events()
    # assert len(events) == 15
    # project_removed_event = next((e for e in events if e.get_message_type() == "project.removed"), None)
    # assert project_removed_event
    # removed_event = deserialize_binary(
    #     b64decode(project_removed_event.payload["payload"]), avro_schema_v2.ProjectRemoved
    # )
    # assert removed_event.id == project_id

    # # Get all projects
    # _, response = await sanic_client.get("/api/data/projects", headers=user_headers)

    # assert response.status_code == 200, response.text
    # assert {p["name"] for p in response.json} == {"Project 1", "Project 2", "Project 4", "Project 5"}
