from typing import Any, Optional

import pytest


@pytest.fixture
def project_owner_member_headers(member_2_headers: dict[str, str]) -> dict[str, str]:
    """Authentication headers for a normal project owner user."""
    return member_2_headers


@pytest.fixture
def project_non_member_headers(unauthorized_headers: dict[str, str]) -> dict[str, str]:
    """Authentication headers for a user that isn't a member of a project."""
    return unauthorized_headers


@pytest.fixture
def project_normal_member_headers(member_1_headers: dict[str, str]) -> dict[str, str]:
    """Authentication headers for a user that isn't a member of a project."""
    return member_1_headers


@pytest.fixture
def create_storage(sanic_client, user_headers, admin_headers, create_project, project_members):
    async def create_storage_helper(project_id: Optional[str] = None, admin: bool = False, **payload) -> dict[str, Any]:
        if not project_id:
            project = await create_project("Project", members=project_members)
            project_id = project["id"]

        headers = admin_headers if admin else user_headers
        storage_payload = {
            "project_id": project_id,
            "name": "my-storage",
            "configuration": {
                "type": "s3",
                "provider": "AWS",
                "region": "us-east-1",
            },
            "source_path": "bucket/my-folder",
            "target_path": "my/target",
        }
        storage_payload.update(payload)

        _, response = await sanic_client.post("/api/data/storages_v2", headers=headers, json=storage_payload)

        assert response.status_code == 201, response.text
        return response.json

    return create_storage_helper


@pytest.mark.asyncio
@pytest.mark.parametrize("headers_name", ["admin_headers", "user_headers", "project_owner_member_headers"])
async def test_storage_v2_can_create_as_admin_or_owner(
    sanic_client, create_project, project_members, headers_name, request
) -> None:
    headers = request.getfixturevalue(headers_name)
    # Create some projects
    await create_project("Project 1")
    project = await create_project("Project 2", members=project_members)
    await create_project("Project 3")

    payload = {
        "project_id": project["id"],
        "name": "my-storage",
        "configuration": {
            "type": "s3",
            "provider": "AWS",
            "region": "us-east-1",
        },
        "source_path": "bucket/my-folder",
        "target_path": "my/target",
    }

    _, response = await sanic_client.post("/api/data/storages_v2", headers=headers, json=payload)

    assert response
    assert response.status_code == 201
    assert response.json
    assert response.json["storage"]["project_id"] == project["id"]
    assert response.json["storage"]["storage_type"] == "s3"
    assert response.json["storage"]["name"] == payload["name"]
    assert response.json["storage"]["target_path"] == payload["target_path"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "headers_name", ["unauthorized_headers", "project_normal_member_headers", "project_non_member_headers"]
)
async def test_storage_v2_create_cannot_as_unauthorized_or_non_owner_or_non_member(
    sanic_client, create_project, project_members, headers_name, request
) -> None:
    headers = request.getfixturevalue(headers_name)
    # Create some projects
    await create_project("Project 1")
    project = await create_project("Project 2", members=project_members)
    await create_project("Project 3")

    payload = {
        "project_id": project["id"],
        "name": "my-storage",
        "configuration": {
            "type": "s3",
            "provider": "AWS",
            "region": "us-east-1",
        },
        "source_path": "bucket/my-folder",
        "target_path": "my/target",
    }

    _, response = await sanic_client.post("/api/data/storages_v2", headers=headers, json=payload)

    assert response
    assert response.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "headers_name", ["admin_headers", "user_headers", "project_normal_member_headers", "project_owner_member_headers"]
)
async def test_storage_v2_can_get_as_admin_or_project_members(
    sanic_client, create_storage, create_project, project_members, headers_name, request
) -> None:
    headers = request.getfixturevalue(headers_name)
    await create_project("Project 1")
    project_2 = await create_project("Project 2", members=project_members)
    project_3 = await create_project("Project 3", members=project_members)

    project_2_id = project_2["id"]

    await create_storage(project_id=project_2_id)

    _, response = await sanic_client.get(f"/api/data/storages_v2?project_id={project_2_id}", headers=headers)

    assert response.status_code == 200
    assert len(response.json) == 1
    storage = response.json[0]["storage"]
    assert storage["project_id"] == project_2_id
    assert storage["storage_type"] == "s3"
    assert storage["configuration"]["provider"] == "AWS"

    _, response = await sanic_client.get(f"/api/data/storages_v2?project_id={project_3['id']}", headers=headers)

    assert response.status_code == 200
    assert len(response.json) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("headers_name", ["unauthorized_headers", "project_non_member_headers"])
async def test_storage_v2_cannot_get_as_unauthorized_or_non_member(
    sanic_client, create_storage, create_project, project_members, headers_name, request
) -> None:
    headers = request.getfixturevalue(headers_name)
    project = await create_project("Project", members=project_members)
    project_id = project["id"]

    await create_storage(project_id=project_id)

    _, response = await sanic_client.get(f"/api/data/storages_v2?project_id={project_id}", headers=headers)

    assert response.status_code == 200
    assert len(response.json) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("headers_name", ["user_headers", "project_owner_member_headers"])
async def test_storage_v2_can_delete_as_owner(sanic_client, create_storage, headers_name, request) -> None:
    headers = request.getfixturevalue(headers_name)
    storage = await create_storage()
    storage_id = storage["storage"]["storage_id"]

    _, response = await sanic_client.delete(f"/api/data/storages_v2/{storage_id}", headers=headers)

    assert response.status_code == 204

    _, response = await sanic_client.get(f"/api/data/storages_v2/{storage_id}", headers=headers)

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_storage_v2_cannot_delete_as_normal_member(
    sanic_client, create_storage, project_normal_member_headers
) -> None:
    storage = await create_storage()
    storage_id = storage["storage"]["storage_id"]

    _, response = await sanic_client.delete(
        f"/api/data/storages_v2/{storage_id}", headers=project_normal_member_headers
    )

    assert response.status_code == 403

    _, response = await sanic_client.get(f"/api/data/storages_v2/{storage_id}", headers=project_normal_member_headers)

    assert response.status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("headers_name", ["unauthorized_headers", "project_non_member_headers"])
async def test_storage_v2_cannot_delete_as_unauthorized_or_non_member(
    sanic_client, create_storage, headers_name, request
) -> None:
    headers = request.getfixturevalue(headers_name)
    storage = await create_storage()
    storage_id = storage["storage"]["storage_id"]

    _, response = await sanic_client.delete(f"/api/data/storages_v2/{storage_id}", headers=headers)

    assert response.status_code == 403, response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("headers_name", ["user_headers", "project_owner_member_headers"])
async def test_storage_v2_can_patch_as_owner(sanic_client, create_storage, headers_name, request) -> None:
    headers = request.getfixturevalue(headers_name)
    storage = await create_storage()
    storage_id = storage["storage"]["storage_id"]

    payload = {
        "configuration": {"provider": "Other", "region": None, "endpoint": "https://test.com"},
        "source_path": "bucket/my-other-folder",
    }

    _, response = await sanic_client.patch(f"/api/data/storages_v2/{storage_id}", headers=headers, json=payload)

    assert response.status_code == 200
    assert response.json["storage"]["configuration"]["provider"] == "Other"
    assert response.json["storage"]["source_path"] == "bucket/my-other-folder"
    assert "region" not in response.json["storage"]["configuration"]


@pytest.mark.asyncio
async def test_storage_v2_cannot_patch_as_normal_member(
    sanic_client, create_storage, project_normal_member_headers
) -> None:
    storage = await create_storage()
    storage_id = storage["storage"]["storage_id"]

    payload = {
        "configuration": {"provider": "Other", "region": None, "endpoint": "https://test.com"},
        "source_path": "bucket/my-other-folder",
    }

    _, response = await sanic_client.patch(
        f"/api/data/storages_v2/{storage_id}", headers=project_normal_member_headers, json=payload
    )

    assert response.status_code == 403

    _, response = await sanic_client.get(f"/api/data/storages_v2/{storage_id}", headers=project_normal_member_headers)

    assert response.status_code == 200
    storage = response.json["storage"]
    assert storage["configuration"]["provider"] == "AWS"
    assert response.json["storage"]["source_path"] == "bucket/my-folder"


@pytest.mark.asyncio
@pytest.mark.parametrize("headers_name", ["unauthorized_headers", "project_non_member_headers"])
async def test_storage_v2_cannot_patch_as_unauthorized_or_non_member(
    sanic_client, create_storage, headers_name, request
) -> None:
    headers = request.getfixturevalue(headers_name)
    storage = await create_storage()
    storage_id = storage["storage"]["storage_id"]

    payload = {
        "configuration": {"provider": "Other", "region": None, "endpoint": "https://test.com"},
        "source_path": "bucket/my-other-folder",
    }

    _, response = await sanic_client.patch(f"/api/data/storages_v2/{storage_id}", headers=headers, json=payload)

    assert response.status_code == 403, response.text


@pytest.mark.asyncio
async def test_storage_v2_is_deleted_if_project_is_deleted(
    sanic_client, create_storage, create_project, user_headers
) -> None:
    project = await create_project("Project")
    project_id = project["id"]
    storage = await create_storage(project_id=project_id)
    storage_id = storage["storage"]["storage_id"]

    _, response = await sanic_client.delete(f"/api/data/projects/{project_id}", headers=user_headers)

    assert response.status_code == 204, response.text

    _, response = await sanic_client.get(f"/api/data/storages_v2/{storage_id}", headers=user_headers)

    # NOTE: If storage isn't deleted, the status code will be 401
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_storage_v2_create_secret(
    sanic_client, create_storage, project_normal_member_headers, project_owner_member_headers
) -> None:
    storage = await create_storage()
    storage_id = storage["storage"]["storage_id"]

    payload = [
        {"name": "access_key_id", "value": "access key id value"},
        {"name": "secret_access_key", "value": "secret access key value"},
    ]

    _, response = await sanic_client.post(
        f"/api/data/storages_v2/{storage_id}/secrets", headers=project_normal_member_headers, json=payload
    )

    assert response.status_code == 201, response.json
    assert {s["name"] for s in response.json} == {"access_key_id", "secret_access_key"}, response.json
    created_secret_ids = {s["secret_id"] for s in response.json}
    assert len(created_secret_ids) == 2, response.json

    # NOTE: Save secrets for the same storage for another user
    payload = [
        {"name": "another_user_secret", "value": "another value"},
    ]

    _, response = await sanic_client.post(
        f"/api/data/storages_v2/{storage_id}/secrets", headers=project_owner_member_headers, json=payload
    )

    assert response.status_code == 201, response.json
    assert {s["name"] for s in response.json} == {"another_user_secret"}, response.json

    # NOTE: Get secrets for a storage
    _, response = await sanic_client.get(
        f"/api/data/storages_v2/{storage_id}/secrets", headers=project_normal_member_headers
    )

    assert response.status_code == 200
    assert {s["name"] for s in response.json} == {"access_key_id", "secret_access_key"}, response.json

    # NOTE: Test that saved secrets are returned when getting a specific storage
    _, response = await sanic_client.get(f"/api/data/storages_v2/{storage_id}", headers=project_normal_member_headers)

    assert response.status_code == 200
    assert "secrets" in response.json, response.json
    assert {s["name"] for s in response.json["secrets"]} == {"access_key_id", "secret_access_key"}, response.json
    assert {s["secret_id"] for s in response.json["secrets"]} == created_secret_ids, response.json

    # NOTE: Test that saved secrets are returned when getting all storages in a project
    assert "project_id" in storage["storage"], storage
    project_id = storage["storage"]["project_id"]
    _, response = await sanic_client.get(
        f"/api/data/storages_v2?project_id={project_id}", headers=project_normal_member_headers
    )

    assert response.status_code == 200
    assert len(response.json) == 1
    assert "secrets" in response.json[0], response.json
    assert {s["name"] for s in response.json[0]["secrets"]} == {"access_key_id", "secret_access_key"}, response.json
    assert {s["secret_id"] for s in response.json[0]["secrets"]} == created_secret_ids, response.json


@pytest.mark.asyncio
async def test_storage_v2_update_secret(sanic_client, create_storage, project_normal_member_headers) -> None:
    storage = await create_storage()
    storage_id = storage["storage"]["storage_id"]

    payload = [
        {"name": "access_key_id", "value": "access key id value"},
        {"name": "secret_access_key", "value": "secret access key value"},
    ]

    _, response = await sanic_client.post(
        f"/api/data/storages_v2/{storage_id}/secrets", headers=project_normal_member_headers, json=payload
    )

    assert response.status_code == 201, response.json
    created_secret_ids = {s["secret_id"] for s in response.json}

    payload = [
        {"name": "access_key_id", "value": "new access key id value"},
        {"name": "secret_access_key", "value": "new secret access key value"},
    ]

    _, response = await sanic_client.post(
        f"/api/data/storages_v2/{storage_id}/secrets", headers=project_normal_member_headers, json=payload
    )

    assert response.status_code == 201, response.json
    assert {s["name"] for s in response.json} == {"access_key_id", "secret_access_key"}, response.json
    assert {s["secret_id"] for s in response.json} == created_secret_ids

    _, response = await sanic_client.get(
        f"/api/data/storages_v2/{storage_id}/secrets", headers=project_normal_member_headers
    )

    assert response.status_code == 200
    assert {s["name"] for s in response.json} == {"access_key_id", "secret_access_key"}, response.json


@pytest.mark.asyncio
async def test_storage_v2_delete_secret(sanic_client, create_storage, project_normal_member_headers) -> None:
    storage = await create_storage()
    storage_id = storage["storage"]["storage_id"]

    payload = [
        {"name": "access_key_id", "value": "access key id value"},
        {"name": "secret_access_key", "value": "secret access key value"},
    ]

    _, response = await sanic_client.post(
        f"/api/data/storages_v2/{storage_id}/secrets", headers=project_normal_member_headers, json=payload
    )

    assert response.status_code == 201, response.json

    _, response = await sanic_client.delete(
        f"/api/data/storages_v2/{storage_id}/secrets", headers=project_normal_member_headers
    )

    assert response.status_code == 204, response.json

    _, response = await sanic_client.get(
        f"/api/data/storages_v2/{storage_id}/secrets", headers=project_normal_member_headers
    )

    assert response.status_code == 200
    assert {s["name"] for s in response.json} == set(), response.json

    # NOTE: Test that associated secrets are deleted
    _, response = await sanic_client.get(
        "/api/data/user/secrets", params={"kind": "storage"}, headers=project_normal_member_headers
    )

    assert response.status_code == 200
    assert response.json == [], response.json

    # TODO: Once saved secret sharing is implemented, add a test that makes sure shared secrets aren't deleted unless
    # no other storage is using them
