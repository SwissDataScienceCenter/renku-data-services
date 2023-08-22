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
    "project_id": "namespace/project",
    "storage_type": "s3",
    "configuration": {
        "provider": "AWS",
        "region": "us-east-1",
    },
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
    "payload,expected_status_code",
    [
        (_valid_storage, 201),
        (
            {
                "project_id": "namespace/project",
                "storage_type": "s3",
                "configuration": {
                    "provider": "AWS",
                    "secret_access_key": "1234567",
                },
            },
            422,
        ),
        (
            {
                "project_id": "namespace/project",
                "storage_type": "s3",
                "configuration": {"provider": "AWS", "region": None},
            },
            422,
        ),
    ],
)
def test_storage_creation(storage_test_client: SanicTestClient, payload: dict[str, Any], expected_status_code: int):
    _, res = storage_test_client.post(
        "/api/storage/storage",
        headers={"Authorization": "bearer test"},
        data=json.dumps(payload),
    )
    assert res
    assert res.status_code == expected_status_code


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
