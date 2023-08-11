import json
from typing import Any

import pytest
from sanic import Sanic
from sanic_testing.testing import SanicTestClient

from renku_data_services.storage_adapters import StorageRepository
from renku_data_services.storage_api.app import register_all_handlers
from renku_data_services.storage_api.config import Config
from renku_data_services.storage_schemas.core import RCloneValidator
from renku_data_services.users.dummy import DummyAuthenticator

_valid_storage: dict[str, Any] = {
    "project_id": "123456",
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
def storage_test_client(storage_repo: StorageRepository) -> SanicTestClient:
    config = Config(
        storage_repo=storage_repo,
        authenticator=DummyAuthenticator(admin=True),
    )

    app = Sanic(config.app_name)
    app = register_all_handlers(app, config)
    app.ext.add_dependency(RCloneValidator)
    return SanicTestClient(app)


@pytest.mark.parametrize(
    "payload,expected_status_code,expected_storage_type",
    [
        (_valid_storage, 201, "s3"),
        (
            {
                "project_id": "123456",
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
                "source_path": "bucket/myfolder",
                "target_path": "my/target",
                "storage_url": "s3://s3.us-east-2.amazonaws.com/mybucket/myfolder",
            },
            201,
            "s3",
        ),
        (
            {
                "project_id": "123456",
                "source_path": "bucket/myfolder",
                "target_path": "my/target",
                "storage_url": "s3://giab/",
            },
            201,
            "s3",
        ),
        (
            {
                "project_id": "123456",
                "source_path": "bucket/myfolder",
                "target_path": "my/target",
                "storage_url": "s3://mybucket.s3.us-east-2.amazonaws.com/myfolder",
            },
            201,
            "s3",
        ),
        (
            {
                "project_id": "123456",
                "target_path": "my/target",
                "storage_url": "https://my.provider.com/mybucket/myfolder",
            },
            201,
            "s3",
        ),
        (
            {
                "project_id": "123456",
                "target_path": "my/target",
                "storage_url": "azure://mycontainer/myfolder",
            },
            201,
            "azureblob",
        ),
        (
            {
                "project_id": "123456",
                "target_path": "my/target",
                "storage_url": "az://myaccount.dfs.core.windows.net/myfolder",
            },
            201,
            "azureblob",
        ),
        (
            {
                "project_id": "123456",
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
                "configuration": {
                    "type": "s3",
                    "provider": "AWS",
                    "secret_access_key": "1234567",
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
                "configuration": {
                    "provider": "AWS",
                    "region": None,
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
                "storage_type": "s3",
                "configuration": {
                    "provider": "AWS",
                    "region": "us-east-1",
                    "type": "s3",
                },
            },
            422,
            "",
        ),
        (
            {
                "project_id": "123456",
                "storage_type": "s3",
                "configuration": {
                    "provider": "AWS",
                    "region": "us-east-1",
                },
                "source_path": "bucket/myfolder",
                "target_path": "my/target",
            },
            422,
            "",
        ),
    ],
)
def test_storage_creation(
    storage_test_client: SanicTestClient, payload: dict[str, Any], expected_status_code: int, expected_storage_type: str
):
    _, res = storage_test_client.post(
        "/api/storage/storage",
        headers={"Authorization": "bearer test"},
        data=json.dumps(payload),
    )
    assert res
    assert res.status_code == expected_status_code
    assert res.json
    if res.status_code < 300:
        assert res.json["storage_type"] == expected_storage_type


def test_get_storage(storage_test_client, valid_storage_payload):
    _, res = storage_test_client.post(
        "/api/storage/storage",
        headers={"Authorization": "bearer test"},
        data=json.dumps(valid_storage_payload),
    )
    assert res.status_code == 201
    assert res.json["storage_type"] == "s3"

    project_id = res.json["project_id"]
    _, res = storage_test_client.get(
        f"/api/storage/storage?project_id={project_id}",
        headers={"Authorization": "bearer test"},
    )
    assert res.status_code == 200
    assert len(res.json) == 1
    assert res.json[0]["project_id"] == project_id
    assert res.json[0]["storage_type"] == "s3"
    assert res.json[0]["configuration"]["provider"] == "AWS"


def test_storage_deletion(storage_test_client, valid_storage_payload):
    _, res = storage_test_client.post(
        "/api/storage/storage",
        headers={"Authorization": "bearer test"},
        data=json.dumps(valid_storage_payload),
    )
    assert res.status_code == 201
    assert res.json["storage_type"] == "s3"
    storage_id = res.json["storage_id"]

    _, res = storage_test_client.delete(
        f"/api/storage/storage/{storage_id}",
        headers={"Authorization": "bearer test"},
    )
    assert res.status_code == 204

    _, res = storage_test_client.get(
        f"/api/storage/storage/{storage_id}",
        headers={"Authorization": "bearer test"},
    )

    assert res.status_code == 404


def test_storage_put(storage_test_client, valid_storage_payload):
    _, res = storage_test_client.post(
        "/api/storage/storage",
        headers={"Authorization": "bearer test"},
        data=json.dumps(valid_storage_payload),
    )
    assert res.status_code == 201
    assert res.json["storage_type"] == "s3"
    storage_id = res.json["storage_id"]

    _, res = storage_test_client.put(
        f"/api/storage/storage/{storage_id}",
        headers={"Authorization": "bearer test"},
        data=json.dumps(
            {
                "project_id": valid_storage_payload["project_id"],
                "configuration": {"type": "azureblob"},
                "source_path": "bucket/myfolder",
                "target_path": "my/target",
            }
        ),
    )
    assert res.status_code == 200
    assert res.json["storage_type"] == "azureblob"


def test_storage_patch(storage_test_client, valid_storage_payload):
    _, res = storage_test_client.post(
        "/api/storage/storage",
        headers={"Authorization": "bearer test"},
        data=json.dumps(valid_storage_payload),
    )
    assert res.status_code == 201
    assert res.json["storage_type"] == "s3"
    storage_id = res.json["storage_id"]

    _, res = storage_test_client.patch(
        f"/api/storage/storage/{storage_id}",
        headers={"Authorization": "bearer test"},
        data=json.dumps(
            {
                "configuration": {"type": "azureblob"},
                "source_path": "bucket/myotherfolder",
            }
        ),
    )
    assert res.status_code == 200
    assert res.json["storage_type"] == "azureblob"
    assert res.json["source_path"] == "bucket/myotherfolder"
