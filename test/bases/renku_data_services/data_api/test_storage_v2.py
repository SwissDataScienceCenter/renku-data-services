from typing import Any, Optional

import pytest


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
):
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
):
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
    assert response.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "headers_name", ["admin_headers", "user_headers", "project_normal_member_headers", "project_owner_member_headers"]
)
async def test_storage_v2_can_get_as_admin_or_project_members(
    sanic_client, create_storage, create_project, project_members, headers_name, request
):
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
):
    headers = request.getfixturevalue(headers_name)
    project = await create_project("Project", members=project_members)
    project_id = project["id"]

    await create_storage(project_id=project_id)

    _, response = await sanic_client.get(f"/api/data/storages_v2?project_id={project_id}", headers=headers)

    assert response.status_code == 200
    assert len(response.json) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("headers_name", ["user_headers", "project_owner_member_headers"])
async def test_storage_v2_can_delete_as_owner(sanic_client, create_storage, headers_name, request):
    headers = request.getfixturevalue(headers_name)
    storage = await create_storage()
    storage_id = storage["storage"]["storage_id"]

    _, response = await sanic_client.delete(f"/api/data/storages_v2/{storage_id}", headers=headers)

    assert response.status_code == 204

    _, response = await sanic_client.get(f"/api/data/storages_v2/{storage_id}", headers=headers)

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_storage_v2_cannot_delete_as_normal_member(sanic_client, create_storage, project_normal_member_headers):
    storage = await create_storage()
    storage_id = storage["storage"]["storage_id"]

    _, response = await sanic_client.delete(
        f"/api/data/storages_v2/{storage_id}", headers=project_normal_member_headers
    )

    assert response.status_code == 401

    _, response = await sanic_client.get(f"/api/data/storages_v2/{storage_id}", headers=project_normal_member_headers)

    assert response.status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("headers_name", ["unauthorized_headers", "project_non_member_headers"])
async def test_storage_v2_cannot_delete_as_unauthorized_or_non_member(
    sanic_client, create_storage, headers_name, request
):
    headers = request.getfixturevalue(headers_name)
    storage = await create_storage()
    storage_id = storage["storage"]["storage_id"]

    _, response = await sanic_client.delete(f"/api/data/storages_v2/{storage_id}", headers=headers)

    assert response.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("headers_name", ["user_headers", "project_owner_member_headers"])
async def test_storage_v2_can_patch_as_owner(sanic_client, create_storage, headers_name, request):
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
async def test_storage_v2_cannot_patch_as_normal_member(sanic_client, create_storage, project_normal_member_headers):
    storage = await create_storage()
    storage_id = storage["storage"]["storage_id"]

    payload = {
        "configuration": {"provider": "Other", "region": None, "endpoint": "https://test.com"},
        "source_path": "bucket/my-other-folder",
    }

    _, response = await sanic_client.patch(
        f"/api/data/storages_v2/{storage_id}", headers=project_normal_member_headers, json=payload
    )

    assert response.status_code == 401

    _, response = await sanic_client.get(f"/api/data/storages_v2/{storage_id}", headers=project_normal_member_headers)

    assert response.status_code == 200
    storage = response.json["storage"]
    assert storage["configuration"]["provider"] == "AWS"
    assert response.json["storage"]["source_path"] == "bucket/my-folder"


@pytest.mark.asyncio
@pytest.mark.parametrize("headers_name", ["unauthorized_headers", "project_non_member_headers"])
async def test_storage_v2_cannot_patch_as_unauthorized_or_non_member(
    sanic_client, create_storage, headers_name, request
):
    headers = request.getfixturevalue(headers_name)
    storage = await create_storage()
    storage_id = storage["storage"]["storage_id"]

    payload = {
        "configuration": {"provider": "Other", "region": None, "endpoint": "https://test.com"},
        "source_path": "bucket/my-other-folder",
    }

    _, response = await sanic_client.patch(f"/api/data/storages_v2/{storage_id}", headers=headers, json=payload)

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_storage_v2_is_deleted_if_project_is_deleted(sanic_client, create_storage, create_project, user_headers):
    project = await create_project("Project")
    project_id = project["id"]
    storage = await create_storage(project_id=project_id)
    storage_id = storage["storage"]["storage_id"]

    _, response = await sanic_client.delete(f"/api/data/projects/{project_id}", headers=user_headers)

    assert response.status_code == 204, response.text

    _, response = await sanic_client.get(f"/api/data/storages_v2/{storage_id}", headers=user_headers)

    # NOTE: If storage isn't deleted, the status code will be 401
    assert response.status_code == 404
