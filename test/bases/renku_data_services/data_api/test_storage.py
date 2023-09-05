import json
from typing import Any

import pytest
from sanic import Sanic
from sanic_testing.testing import SanicASGITestClient

from renku_data_services.data_api.app import register_all_handlers
from renku_data_services.data_api.config import Config
from renku_data_services.k8s.clients import DummyCoreClient, DummySchedulingClient
from renku_data_services.k8s.quota import QuotaRepository
from renku_data_services.resource_pool_adapters import ResourcePoolRepository, UserRepository
from renku_data_services.storage_adapters import StorageRepository
from renku_data_services.storage_schemas.core import RCloneValidator
from renku_data_services.users.dummy import DummyAuthenticator, DummyUserStore

_valid_storage: dict[str, Any] = {
    "project_id": "123456",
    "name": "mystorage",
    "configuration": {
        "type": "s3",
        "provider": "AWS",
        "region": "us-east-1",
    },
    "source_path": "bucket/myfolder",
    "target_path": "my/target",
}


@pytest.fixture
def valid_storage_payload() -> dict[str, Any]:
    return _valid_storage


@pytest.fixture
def storage_test_client(
    storage_repo: StorageRepository, pool_repo: ResourcePoolRepository, user_repo: UserRepository
) -> SanicASGITestClient:
    gitlab_auth = DummyAuthenticator(admin=True, gitlab=True)
    config = Config(
        user_repo=user_repo,
        rp_repo=pool_repo,
        storage_repo=storage_repo,
        user_store=DummyUserStore(),
        authenticator=DummyAuthenticator(admin=True),
        gitlab_authenticator=gitlab_auth,
        quota_repo=QuotaRepository(DummyCoreClient({}), DummySchedulingClient({})),
    )

    app = Sanic(config.app_name)
    app = register_all_handlers(app, config)
    app.ext.add_dependency(RCloneValidator)
    return SanicASGITestClient(app), gitlab_auth


@pytest.mark.parametrize(
    "payload,expected_status_code,expected_storage_type",
    [
        (_valid_storage, 201, "s3"),
        (
            {
                "project_id": "123456",
                "name": "mystorage",
                "configuration": {
                    "type": "s3",
                    "provider": "AWS",
                    "region": "us-east-1",
                },
                "source_path": "bucket/myfolder",
                "target_path": "my/target",
            },
            201,
            "s3",
        ),
        (
            {
                "project_id": "123456",
                "name": "mystorage",
                "target_path": "my/target",
                "storage_url": "s3://s3.us-east-2.amazonaws.com/mybucket/myfolder",
            },
            201,
            "s3",
        ),
        (
            {
                "project_id": "123456",
                "name": "mystorage",
                "target_path": "my/target",
                "storage_url": "s3://giab/",
            },
            201,
            "s3",
        ),
        (
            {
                "project_id": "123456",
                "name": "mystorage",
                "target_path": "my/target",
                "storage_url": "s3://mybucket.s3.us-east-2.amazonaws.com/myfolder",
            },
            201,
            "s3",
        ),
        (
            {
                "project_id": "123456",
                "name": "mystorage",
                "target_path": "my/target",
                "storage_url": "https://my.provider.com/mybucket/myfolder",
            },
            201,
            "s3",
        ),
        (
            {
                "project_id": "123456",
                "name": "mystorage",
                "target_path": "my/target",
                "storage_url": "azure://mycontainer/myfolder",
            },
            201,
            "azureblob",
        ),
        (
            {
                "project_id": "123456",
                "name": "mystorage",
                "target_path": "my/target",
                "storage_url": "az://myaccount.dfs.core.windows.net/myfolder",
            },
            201,
            "azureblob",
        ),
        (
            {
                "project_id": "123456",
                "name": "mystorage",
                "source_path": "bucket/myfolder",
                "target_path": "my/target",
                "storage_url": "az://myaccount.blob.core.windows.net/myfolder",
            },
            201,
            "azureblob",
        ),
        (
            {
                "project_id": "123456",
                "name": "mystorage",
                "configuration": {
                    "type": "s3",
                    "provider": "AWS",
                    "secret_access_key": "1234567",  # passing in secret
                },
                "source_path": "bucket/myfolder",
                "target_path": "my/target",
                "private": False,
            },
            422,
            "",
        ),
        (
            {
                "project_id": "123456",
                "name": "mystorage",
                "configuration": {
                    "type": "s3",
                    "provider": "AWS",
                    "secret_access_key": "1234567",  # passing in secret
                },
                "source_path": "bucket/myfolder",
                "target_path": "my/target",
                "private": True,
            },
            201,
            "s3",
        ),
        (
            {
                "project_id": "123456",
                "name": "mystorage",
                "configuration": {
                    "provider": "Petabox",
                    "type": "s3",
                },
                "source_path": "bucket/myfolder",
                "target_path": "my/target",
            },
            422,
            "",
        ),
        (
            {
                "project_id": "123456",
                "name": "mystorage",
                "storage_type": "s3",
                "configuration": {
                    "provider": "AWS",
                    "region": "us-east-1",
                    "type": "s3",
                },  # mising source/target path
            },
            422,
            "",
        ),
        (
            {
                "project_id": "123456",
                "name": "mystorage",
                "storage_type": "s3",
                "configuration": {  # missing type in config
                    "provider": "AWS",
                    "region": "us-east-1",
                },
                "source_path": "bucket/myfolder",
                "target_path": "my/target",
            },
            422,
            "",
        ),
        (
            {
                "project_id": "999999",  # unauthorized storage id
                "name": "mystorage",
                "configuration": {
                    "type": "s3",
                    "provider": "AWS",
                    "region": "us-east-1",
                },
                "source_path": "bucket/myfolder",
                "target_path": "my/target",
            },
            401,
            "",
        ),
        (
            {  # no name
                "project_id": "123456",
                "configuration": {
                    "type": "s3",
                    "provider": "AWS",
                    "region": "us-east-1",
                },
                "source_path": "bucket/my-folder",
                "target_path": "my/my-target",
            },
            422,
            "",
        ),
    ],
)
@pytest.mark.asyncio
async def test_storage_creation(
    storage_test_client: SanicASGITestClient,
    payload: dict[str, Any],
    expected_status_code: int,
    expected_storage_type: str,
):
    storage_test_client, _ = storage_test_client
    _, res = await storage_test_client.post(
        "/api/data/storage",
        headers={"Authorization": "bearer test"},
        data=json.dumps(payload),
    )
    assert res
    assert res.status_code == expected_status_code
    assert res.json
    if res.status_code < 300:
        assert res.json["storage"]["storage_type"] == expected_storage_type
        assert res.json["storage"]["name"] == payload["name"]
        assert res.json["storage"]["target_path"] == payload["target_path"]


@pytest.mark.asyncio
async def test_create_storage_duplicate_name(storage_test_client, valid_storage_payload):
    storage_test_client, _ = storage_test_client
    _, res = await storage_test_client.post(
        "/api/data/storage",
        headers={"Authorization": "bearer test"},
        data=json.dumps(valid_storage_payload),
    )
    assert res.status_code == 201
    assert res.json["storage"]["storage_type"] == "s3"

    _, res = await storage_test_client.post(
        "/api/data/storage",
        headers={"Authorization": "bearer test"},
        data=json.dumps(valid_storage_payload),
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_get_storage(storage_test_client, valid_storage_payload):
    storage_test_client, _ = storage_test_client
    _, res = await storage_test_client.post(
        "/api/data/storage",
        headers={"Authorization": "bearer test"},
        data=json.dumps(valid_storage_payload),
    )
    assert res.status_code == 201
    assert res.json["storage"]["storage_type"] == "s3"

    project_id = res.json["storage"]["project_id"]
    _, res = await storage_test_client.get(
        f"/api/data/storage?project_id={project_id}",
        headers={"Authorization": "bearer test"},
    )
    assert res.status_code == 200
    assert len(res.json) == 1
    result = res.json[0]
    storage = result["storage"]
    assert storage["project_id"] == project_id
    assert storage["storage_type"] == "s3"
    assert storage["configuration"]["provider"] == "AWS"


@pytest.mark.asyncio
async def test_get_storage_unauthorized(storage_test_client, valid_storage_payload):
    storage_test_client, gl_auth = storage_test_client
    _, res = await storage_test_client.post(
        "/api/data/storage",
        headers={"Authorization": "bearer test"},
        data=json.dumps(valid_storage_payload),
    )
    assert res.status_code == 201
    assert res.json["storage"]["storage_type"] == "s3"

    project_id = res.json["storage"]["project_id"]
    gl_auth.project_id = "9999999"
    _, res = await storage_test_client.get(
        f"/api/data/storage?project_id={project_id}",
        headers={"Authorization": "bearer test"},
    )
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_get_storage_private(storage_test_client, valid_storage_payload):
    storage_test_client, _ = storage_test_client
    valid_storage_payload["private"] = True

    _, res = await storage_test_client.post(
        "/api/data/storage",
        headers={"Authorization": "bearer test"},
        data=json.dumps(valid_storage_payload),
    )
    assert res.status_code == 201
    assert res.json["storage"]["storage_type"] == "s3"

    project_id = res.json["storage"]["project_id"]
    _, res = await storage_test_client.get(
        f"/api/data/storage?project_id={project_id}",
        headers={"Authorization": "bearer test"},
    )
    assert res.status_code == 200
    assert len(res.json) == 1
    result = res.json[0]
    assert "sensitive_fields" in result
    assert len(result["sensitive_fields"]) == 3
    assert any(f["name"] == "access_key_id" for f in result["sensitive_fields"])
    storage = result["storage"]
    assert storage["project_id"] == project_id
    assert storage["storage_type"] == "s3"
    assert storage["configuration"]["provider"] == "AWS"


@pytest.mark.asyncio
async def test_storage_deletion(storage_test_client, valid_storage_payload):
    storage_test_client, _ = storage_test_client
    _, res = await storage_test_client.post(
        "/api/data/storage",
        headers={"Authorization": "bearer test"},
        data=json.dumps(valid_storage_payload),
    )
    assert res.status_code == 201
    assert res.json["storage"]["storage_type"] == "s3"
    storage_id = res.json["storage"]["storage_id"]

    _, res = await storage_test_client.delete(
        f"/api/data/storage/{storage_id}",
        headers={"Authorization": "bearer test"},
    )
    assert res.status_code == 204

    _, res = await storage_test_client.get(
        f"/api/data/storage/{storage_id}",
        headers={"Authorization": "bearer test"},
    )

    assert res.status_code == 404


@pytest.mark.asyncio
async def test_storage_deletion_unauthorized(storage_test_client, valid_storage_payload):
    storage_test_client, gl_auth = storage_test_client
    _, res = await storage_test_client.post(
        "/api/data/storage",
        headers={"Authorization": "bearer test"},
        data=json.dumps(valid_storage_payload),
    )
    assert res.status_code == 201
    assert res.json["storage"]["storage_type"] == "s3"
    storage_id = res.json["storage"]["storage_id"]
    gl_auth.project_id = "999999"
    _, res = await storage_test_client.delete(
        f"/api/data/storage/{storage_id}",
        headers={"Authorization": "bearer test"},
    )
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_storage_put(storage_test_client, valid_storage_payload):
    storage_test_client, _ = storage_test_client
    _, res = await storage_test_client.post(
        "/api/data/storage",
        headers={"Authorization": "bearer test"},
        data=json.dumps(valid_storage_payload),
    )
    assert res.status_code == 201
    assert res.json["storage"]["storage_type"] == "s3"
    storage_id = res.json["storage"]["storage_id"]

    _, res = await storage_test_client.put(
        f"/api/data/storage/{storage_id}",
        headers={"Authorization": "bearer test"},
        data=json.dumps(
            {
                "project_id": valid_storage_payload["project_id"],
                "name": "newstoragename",
                "configuration": {"type": "azureblob"},
                "source_path": "bucket/myfolder",
                "target_path": "my/target",
                "private": True,
            }
        ),
    )
    assert res.status_code == 200
    assert res.json["storage"]["storage_type"] == "azureblob"
    assert res.json["storage"]["private"]


@pytest.mark.asyncio
async def test_storage_patch_make_public(storage_test_client):
    payload = {
        "project_id": "123456",
        "name": "mystorage",
        "configuration": {"type": "s3", "provider": "AWS", "region": "us-east-1", "access_key_id": "my-secret"},
        "source_path": "bucket/myfolder",
        "target_path": "my/target",
        "private": "true",
    }
    storage_test_client, _ = storage_test_client
    _, res = await storage_test_client.post(
        "/api/data/storage",
        headers={"Authorization": "bearer test"},
        data=json.dumps(payload),
    )
    assert res.status_code == 201
    assert res.json["storage"]["storage_type"] == "s3"
    assert res.json["storage"]["private"]
    assert "access_key_id" in res.json["storage"]["configuration"]
    storage_id = res.json["storage"]["storage_id"]

    _, res = await storage_test_client.patch(
        f"/api/data/storage/{storage_id}",
        headers={"Authorization": "bearer test"},
        data=json.dumps(
            {
                "private": False,
            }
        ),
    )
    assert res.status_code == 200
    assert not res.json["storage"]["private"]
    assert "access_key_id" not in res.json["storage"]["configuration"]


@pytest.mark.asyncio
async def test_storage_put_unauthorized(storage_test_client, valid_storage_payload):
    storage_test_client, gl_auth = storage_test_client
    _, res = await storage_test_client.post(
        "/api/data/storage",
        headers={"Authorization": "bearer test"},
        data=json.dumps(valid_storage_payload),
    )
    assert res.status_code == 201
    assert res.json["storage"]["storage_type"] == "s3"
    storage_id = res.json["storage"]["storage_id"]
    gl_auth.project_id = "999999"
    _, res = await storage_test_client.put(
        f"/api/data/storage/{storage_id}",
        headers={"Authorization": "bearer test"},
        data=json.dumps(
            {
                "project_id": valid_storage_payload["project_id"],
                "name": "newstoragename",
                "configuration": {"type": "azureblob"},
                "source_path": "bucket/myfolder",
                "target_path": "my/target",
            }
        ),
    )
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_storage_patch(storage_test_client, valid_storage_payload):
    storage_test_client, _ = storage_test_client
    _, res = await storage_test_client.post(
        "/api/data/storage",
        headers={"Authorization": "bearer test"},
        data=json.dumps(valid_storage_payload),
    )
    assert res.status_code == 201
    assert res.json["storage"]["storage_type"] == "s3"
    storage_id = res.json["storage"]["storage_id"]

    _, res = await storage_test_client.patch(
        f"/api/data/storage/{storage_id}",
        headers={"Authorization": "bearer test"},
        data=json.dumps(
            {
                "configuration": {"type": "azureblob", "region": None},
                "source_path": "bucket/myotherfolder",
            }
        ),
    )
    assert res.status_code == 200
    assert res.json["storage"]["storage_type"] == "azureblob"
    assert res.json["storage"]["source_path"] == "bucket/myotherfolder"
    assert "region" not in res.json["storage"]["configuration"]


@pytest.mark.asyncio
async def test_storage_patch_unauthorized(storage_test_client, valid_storage_payload):
    storage_test_client, gl_auth = storage_test_client
    _, res = await storage_test_client.post(
        "/api/data/storage",
        headers={"Authorization": "bearer test"},
        data=json.dumps(valid_storage_payload),
    )
    assert res.status_code == 201
    assert res.json["storage"]["storage_type"] == "s3"
    storage_id = res.json["storage"]["storage_id"]
    gl_auth.project_id = "999999"
    _, res = await storage_test_client.patch(
        f"/api/data/storage/{storage_id}",
        headers={"Authorization": "bearer test"},
        data=json.dumps(
            {
                "configuration": {"type": "azureblob"},
                "source_path": "bucket/myotherfolder",
            }
        ),
    )
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_storage_validate_success(storage_test_client):
    storage_test_client, _ = storage_test_client
    body = {"type": "s3", "provider": "Other", "endpoint": "example.com", "access_key_id": "abcdefg"}
    _, res = await storage_test_client.post("/api/data/storage_schema/validate", data=json.dumps(body))
    assert res.status_code == 204


@pytest.mark.asyncio
async def test_storage_validate_error(storage_test_client):
    storage_test_client, _ = storage_test_client
    body = {"type": "s3", "provider": "Other"}
    _, res = await storage_test_client.post("/api/data/storage_schema/validate", data=json.dumps(body))
    assert res.status_code == 422
    assert "missing:\nendpoint" in res.json["error"]["message"]


@pytest.mark.asyncio
async def test_storage_validate_error_sensitive(storage_test_client):
    storage_test_client, _ = storage_test_client
    body = {"type": "s3", "provider": "Other", "endpoint": "example.com", "access_key_id": 5}
    _, res = await storage_test_client.post("/api/data/storage_schema/validate", data=json.dumps(body))
    assert res.status_code == 422
    assert "Value '5' for field 'access_key_id' is not of type string" in res.json["error"]["message"]
