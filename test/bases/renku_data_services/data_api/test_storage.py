import json
from typing import Any, Dict

import pytest
from sanic import Sanic
from sanic_testing.testing import SanicASGITestClient

from renku_data_services.authn.dummy import DummyAuthenticator
from renku_data_services.config import Config
from renku_data_services.data_api.app import register_all_handlers
from renku_data_services.storage.rclone import RCloneValidator

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
def admin_user_headers() -> Dict[str, str]:
    return {"Authorization": "Bearer some-token**ADMIN**"}


@pytest.fixture
def storage_test_client(app_config: Config) -> SanicASGITestClient:
    gitlab_auth = DummyAuthenticator()
    app_config.gitlab_authenticator = gitlab_auth
    app = Sanic(app_config.app_name)
    app = register_all_handlers(app, app_config)
    validator = RCloneValidator()
    app.ext.dependency(validator)
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
                "readonly": False,
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
                "readonly": True,
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
                "readonly": True,
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
                "project_id": "00000",  # unauthorized storage id
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
    admin_user_headers: Dict[str, str],
):
    storage_test_client, _ = storage_test_client
    _, res = await storage_test_client.post(
        "/api/data/storage",
        headers=admin_user_headers,
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
async def test_create_storage_duplicate_name(storage_test_client, valid_storage_payload, admin_user_headers):
    storage_test_client, _ = storage_test_client
    _, res = await storage_test_client.post(
        "/api/data/storage",
        headers=admin_user_headers,
        data=json.dumps(valid_storage_payload),
    )
    assert res.status_code == 201
    assert res.json["storage"]["storage_type"] == "s3"

    _, res = await storage_test_client.post(
        "/api/data/storage",
        headers=admin_user_headers,
        data=json.dumps(valid_storage_payload),
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_get_storage(storage_test_client, valid_storage_payload, admin_user_headers):
    storage_test_client, _ = storage_test_client
    _, res = await storage_test_client.post(
        "/api/data/storage",
        headers=admin_user_headers,
        data=json.dumps(valid_storage_payload),
    )
    assert res.status_code == 201
    assert res.json["storage"]["storage_type"] == "s3"

    project_id = res.json["storage"]["project_id"]
    _, res = await storage_test_client.get(
        f"/api/data/storage?project_id={project_id}",
        headers=admin_user_headers,
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
    _, res = await storage_test_client.get(
        f"/api/data/storage?project_id={project_id}",
        headers={"Authorization": '{"name": "Unauthorized"}'},
    )
    assert res.status_code == 200
    assert len(res.json) == 0


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
    _, res = await storage_test_client.delete(
        f"/api/data/storage/{storage_id}",
        headers={"Authorization": '{"name": "Unauthorized"}'},
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
            }
        ),
    )
    assert res.status_code == 200
    assert res.json["storage"]["storage_type"] == "azureblob"


@pytest.mark.asyncio
async def test_storage_patch_make_public(storage_test_client):
    payload = {
        "project_id": "123456",
        "name": "mystorage",
        "configuration": {"type": "s3", "provider": "AWS", "region": "us-east-1", "access_key_id": "my-secret"},
        "source_path": "bucket/myfolder",
        "target_path": "my/target",
    }
    storage_test_client, _ = storage_test_client
    _, res = await storage_test_client.post(
        "/api/data/storage",
        headers={"Authorization": "bearer test"},
        data=json.dumps(payload),
    )
    assert res.status_code == 201
    assert res.json["storage"]["storage_type"] == "s3"
    assert "access_key_id" in res.json["storage"]["configuration"]
    storage_id = res.json["storage"]["storage_id"]

    _, res = await storage_test_client.patch(
        f"/api/data/storage/{storage_id}",
        headers={"Authorization": "bearer test"},
        data=json.dumps({}),
    )
    assert res.status_code == 200
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
    _, res = await storage_test_client.put(
        f"/api/data/storage/{storage_id}",
        headers={"Authorization": '{"name": "Unauthorized"}'},
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
                "configuration": {"provider": "Other", "region": None},
                "source_path": "bucket/myotherfolder",
            }
        ),
    )
    assert res.status_code == 422
    assert "endpoint" in res.text

    _, res = await storage_test_client.patch(
        f"/api/data/storage/{storage_id}",
        headers={"Authorization": "bearer test"},
        data=json.dumps(
            {
                "configuration": {"provider": "Other", "region": None, "endpoint": "https://test.com"},
                "source_path": "bucket/myotherfolder",
            }
        ),
    )
    assert res.status_code == 200
    assert res.json["storage"]["configuration"]["provider"] == "Other"
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
    _, res = await storage_test_client.patch(
        f"/api/data/storage/{storage_id}",
        headers={"Authorization": '{"name": "Unauthorized"}'},
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
async def test_storage_validate_connection(storage_test_client):
    storage_test_client, _ = storage_test_client
    body = {"configuration": {"type": "s3", "provider": "AWS"}}
    _, res = await storage_test_client.post("/api/data/storage_schema/test_connection", data=json.dumps(body))
    assert res.status_code == 422

    body = {"configuration": {"type": "s3", "provider": "AWS"}, "source_path": "doesntexistatall/"}
    _, res = await storage_test_client.post("/api/data/storage_schema/test_connection", data=json.dumps(body))
    assert res.status_code == 422

    body = {"configuration": {"type": "s3", "provider": "AWS"}, "source_path": "giab/"}
    _, res = await storage_test_client.post("/api/data/storage_schema/test_connection", data=json.dumps(body))
    assert res.status_code == 204


@pytest.mark.asyncio
async def test_storage_validate_error(storage_test_client):
    storage_test_client, _ = storage_test_client

    _, res = await storage_test_client.post("/api/data/storage_schema/validate")
    assert res.status_code == 422

    _, res = await storage_test_client.post("/api/data/storage_schema/validate", data="test")
    assert res.status_code == 400

    _, res = await storage_test_client.post("/api/data/storage_schema/validate", data="{}")
    assert res.status_code == 422

    body = {"type": "s3", "provider": "Other"}
    _, res = await storage_test_client.post("/api/data/storage_schema/validate", data=json.dumps(body))
    assert res.status_code == 422
    assert "missing:\nendpoint" in res.json["error"]["message"]


@pytest.mark.asyncio
async def test_storage_validate_error_wrong_type(storage_test_client):
    storage_test_client, _ = storage_test_client
    body = {"type": "doesntexist"}
    _, res = await storage_test_client.post("/api/data/storage_schema/validate", data=json.dumps(body))
    assert res.status_code == 422
    assert "does not exist" in res.json["error"]["message"]

    body = {"type": "local"}
    _, res = await storage_test_client.post("/api/data/storage_schema/validate", data=json.dumps(body))
    assert res.status_code == 422
    assert "local" in res.json["error"]["message"]


@pytest.mark.asyncio
async def test_storage_validate_error_sensitive(storage_test_client):
    storage_test_client, _ = storage_test_client
    body = {"type": "s3", "provider": "Other", "endpoint": "example.com", "access_key_id": 5}
    _, res = await storage_test_client.post("/api/data/storage_schema/validate", data=json.dumps(body))
    assert res.status_code == 422
    assert "Value '5' for field 'access_key_id' is not of type string" in res.json["error"]["message"]


@pytest.mark.asyncio
async def test_storage_schema(storage_test_client):
    storage_test_client, _ = storage_test_client
    _, res = await storage_test_client.get("/api/data/storage_schema")
    assert res.status_code == 200
    assert not next((e for e in res.json if e["prefix"] == "alias"), None)  # prohibited storage
    s3 = next(e for e in res.json if e["prefix"] == "s3")
    assert s3
    providers = next(p for p in s3["options"] if p["name"] == "provider")
    assert providers
    assert providers.get("examples")
