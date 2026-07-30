import json
from typing import Any

import pytest
import pytest_asyncio
from sanic import Sanic
from sanic_testing.testing import SanicASGITestClient

from renku_data_services.authn.dummy import DummyAuthenticator
from renku_data_services.data_api.app import register_all_handlers
from renku_data_services.data_api.dependencies import DependencyManager
from renku_data_services.migrations.core import run_migrations_for_app
from renku_data_services.storage.constants import BLOCKED_OPTIONS, BLOCKED_STORAGES
from renku_data_services.storage.rclone import RCloneValidator
from renku_data_services.utils.core import get_openbis_session_token
from test.utils import SanicReusableASGITestClient

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


@pytest_asyncio.fixture(scope="session")
async def storage_test_client_setup(app_manager: DependencyManager) -> SanicASGITestClient:
    gitlab_auth = DummyAuthenticator()
    app_manager.gitlab_authenticator = gitlab_auth
    app = Sanic(app_manager.app_name)
    app = register_all_handlers(app, app_manager)
    validator = RCloneValidator()
    app.ext.dependency(validator)
    async with SanicReusableASGITestClient(app) as client:
        yield client, gitlab_auth


@pytest_asyncio.fixture
async def storage_test_client(
    storage_test_client_setup,
    app_manager_instance: DependencyManager,
) -> SanicASGITestClient:
    run_migrations_for_app("common")
    yield storage_test_client_setup


@pytest.mark.asyncio
async def test_storage_obscure(storage_test_client) -> None:
    storage_test_client, _ = storage_test_client
    body = {
        "configuration": {
            "type": "webdav",
            "provider": "Other",
            "user": "abcdefg",
            "pass": "123456",
        }
    }
    _, res = await storage_test_client.post("/api/data/storage_schema/obscure", data=json.dumps(body))
    assert res.status_code == 200
    assert res.json["type"] == "webdav"
    assert res.json["user"] == "abcdefg"
    assert res.json["pass"] != "123456"
    assert len(res.json["pass"]) == 30


@pytest.mark.asyncio
async def test_storage_validate_success(storage_test_client) -> None:
    storage_test_client, _ = storage_test_client
    body = {"type": "s3", "provider": "Other", "endpoint": "example.com", "access_key_id": "abcdefg"}
    _, res = await storage_test_client.post("/api/data/storage_schema/validate", data=json.dumps(body))
    assert res.status_code == 204


@pytest.mark.asyncio
async def test_storage_validate_connection(storage_test_client) -> None:
    storage_test_client, _ = storage_test_client
    body = {"configuration": {"type": "s3", "provider": "AWS"}}
    _, res = await storage_test_client.post("/api/data/storage_schema/test_connection", data=json.dumps(body))
    assert res.status_code == 422

    body = {"configuration": {"type": "s3", "provider": "AWS"}, "source_path": "does_not_exist_at_all/"}
    _, res = await storage_test_client.post("/api/data/storage_schema/test_connection", data=json.dumps(body))
    assert res.status_code == 422

    body = {"configuration": {"type": "s3", "provider": "AWS"}, "source_path": "giab/"}
    _, res = await storage_test_client.post("/api/data/storage_schema/test_connection", data=json.dumps(body))
    assert res.status_code == 204


@pytest.mark.external_service_skip(1 == 1, reason="Depends on a remote openBIS host which may not always be available.")
@pytest.mark.asyncio
async def test_openbis_storage_validate_connection(storage_test_client) -> None:
    openbis_session_token = await get_openbis_session_token(
        openbis_host="openbis-eln-lims.ethz.ch",  # Public openBIS demo instance.
        username="observer",
        password="1234",
    )
    storage_test_client, _ = storage_test_client

    body = {
        "configuration": {
            "type": "openbis",
            "host": "openbis-eln-lims.ethz.ch",
            "session_token": openbis_session_token,
        },
        "source_path": "does_not_exist_at_all/",
    }
    _, res = await storage_test_client.post("/api/data/storage_schema/test_connection", data=json.dumps(body))
    assert res.status_code == 422

    body = {
        "configuration": {
            "type": "openbis",
            "host": "openbis-eln-lims.ethz.ch",
            "session_token": openbis_session_token,
        },
        "source_path": "/",
    }
    _, res = await storage_test_client.post("/api/data/storage_schema/test_connection", data=json.dumps(body))
    assert res.status_code == 204


@pytest.mark.asyncio
async def test_storage_validate_error(storage_test_client) -> None:
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
async def test_storage_validate_error_wrong_type(storage_test_client) -> None:
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
async def test_storage_validate_error_sensitive(storage_test_client) -> None:
    storage_test_client, _ = storage_test_client
    body = {"type": "s3", "provider": "Other", "endpoint": "example.com", "access_key_id": 5}
    _, res = await storage_test_client.post("/api/data/storage_schema/validate", data=json.dumps(body))
    assert res.status_code == 422
    assert "Value '5' for field 'access_key_id' is not of type string" in res.json["error"]["message"]


@pytest.mark.asyncio
async def test_storage_schema_patches(storage_test_client, snapshot) -> None:
    storage_test_client, _ = storage_test_client
    _, res = await storage_test_client.get("/api/data/storage_schema")
    assert res.status_code == 200, res.text
    schema = res.json
    assert not next((e for e in schema if e["prefix"] == "alias"), None)  # prohibited storage
    s3 = next(e for e in schema if e["prefix"] == "s3")
    assert s3
    providers = next(p for p in s3["options"] if p["name"] == "provider")
    assert providers
    assert providers.get("examples")

    # check that switch provider is added to s3
    assert any(e["value"] == "Switch" for e in providers.get("examples"))

    # assert banned storage is not in schema
    assert all(s["prefix"] not in BLOCKED_STORAGES for s in schema)

    # assert webdav password is sensitive
    webdav = next((e for e in schema if e["prefix"] == "webdav"), None)
    assert webdav
    pwd = next((o for o in webdav["options"] if o["name"] == "pass"), None)
    assert pwd
    assert pwd.get("sensitive")

    # ensure that the endpoint is required for custom s3 storage
    endpoints = [
        o
        for o in s3["options"]
        if o["name"] == "endpoint" and o["provider"].startswith("!AWS,ArvanCloud,IBMCOS,IDrive,IONOS,")
    ]
    assert endpoints
    assert all(e.get("required") for e in endpoints)

    # check custom webdav storage is added
    assert any(s["prefix"] == "polybox" for s in schema)
    assert any(s["prefix"] == "switchDrive" for s in schema)

    # check that unsafe SFTP options are removed
    sftp = next((e for e in schema if e["prefix"] == "sftp"), None)
    assert sftp
    assert all(o["name"] not in BLOCKED_OPTIONS["sftp"] for o in sftp["options"])
    webdav = next((e for e in schema if e["prefix"] == "webdav"), None)
    assert webdav
    assert all(o["name"] not in BLOCKED_OPTIONS["webdav"] for o in webdav["options"])

    # snapshot the schema
    assert schema == snapshot


@pytest.mark.asyncio
async def test_storage_validate_connection_supports_doi(storage_test_client) -> None:
    storage_test_client, _ = storage_test_client
    payload = {"configuration": {"type": "doi", "doi": "10.5281/zenodo.15174623"}, "source_path": ""}
    _, res = await storage_test_client.post("/api/data/storage_schema/test_connection", json=payload)
    assert res.status_code == 204, res.text
