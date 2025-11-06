import json
from typing import Any

import pytest
import pytest_asyncio
from sanic import Sanic
from sanic_testing.testing import SanicASGITestClient
from syrupy.filters import props

from renku_data_services.authn.dummy import DummyAuthenticator
from renku_data_services.data_api.app import register_all_handlers
from renku_data_services.data_api.dependencies import DependencyManager
from renku_data_services.migrations.core import run_migrations_for_app
from renku_data_services.storage.rclone import RCloneValidator
from renku_data_services.storage.rclone_patches import BANNED_SFTP_OPTIONS, BANNED_STORAGE, OAUTH_PROVIDERS
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
            201,
            "s3",
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
            403,
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
        (
            {
                "project_id": "123456",
                "name": "mystorage",
                "configuration": {
                    "type": "sftp",
                    "host": "myhost",
                    "ssh": "ssh",  # passing in banned option
                },
                "source_path": "bucket/myfolder",
                "target_path": "my/target",
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
    admin_headers: dict[str, str],
    snapshot,
) -> None:
    storage_test_client, _ = storage_test_client
    _, res = await storage_test_client.post(
        "/api/data/storage",
        headers=admin_headers,
        data=json.dumps(payload),
    )
    assert res
    assert res.status_code == expected_status_code
    assert res.json
    if res.status_code < 300:
        assert res.json["storage"]["storage_type"] == expected_storage_type
        assert res.json["storage"]["name"] == payload["name"]
        assert res.json["storage"]["target_path"] == payload["target_path"]
        assert res.json == snapshot(exclude=props("storage_id"))


@pytest.mark.asyncio
async def test_create_storage_duplicate_name(storage_test_client, valid_storage_payload, admin_headers) -> None:
    storage_test_client, _ = storage_test_client
    _, res = await storage_test_client.post(
        "/api/data/storage",
        headers=admin_headers,
        data=json.dumps(valid_storage_payload),
    )
    assert res.status_code == 201
    assert res.json["storage"]["storage_type"] == "s3"

    _, res = await storage_test_client.post(
        "/api/data/storage",
        headers=admin_headers,
        data=json.dumps(valid_storage_payload),
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_get_storage(storage_test_client, valid_storage_payload, admin_headers) -> None:
    storage_test_client, _ = storage_test_client
    _, res = await storage_test_client.post(
        "/api/data/storage",
        headers=admin_headers,
        data=json.dumps(valid_storage_payload),
    )
    assert res.status_code == 201
    assert res.json["storage"]["storage_type"] == "s3"

    project_id = res.json["storage"]["project_id"]
    _, res = await storage_test_client.get(
        f"/api/data/storage?project_id={project_id}",
        headers=admin_headers,
    )
    assert res.status_code == 200
    assert len(res.json) == 1
    result = res.json[0]
    storage = result["storage"]
    assert storage["project_id"] == project_id
    assert storage["storage_type"] == "s3"
    assert storage["configuration"]["provider"] == "AWS"


@pytest.mark.asyncio
async def test_get_storage_unauthorized(storage_test_client, valid_storage_payload, admin_headers) -> None:
    storage_test_client, gl_auth = storage_test_client
    _, res = await storage_test_client.post(
        "/api/data/storage",
        headers=admin_headers,
        data=json.dumps(valid_storage_payload),
    )
    assert res.status_code == 201
    assert res.json["storage"]["storage_type"] == "s3"

    project_id = res.json["storage"]["project_id"]
    _, res = await storage_test_client.get(
        f"/api/data/storage?project_id={project_id}",
        headers={"Authorization": ""},
    )
    assert res.status_code == 200
    assert len(res.json) == 0


@pytest.mark.asyncio
async def test_storage_deletion(storage_test_client, valid_storage_payload, admin_headers) -> None:
    storage_test_client, _ = storage_test_client
    _, res = await storage_test_client.post(
        "/api/data/storage",
        headers=admin_headers,
        data=json.dumps(valid_storage_payload),
    )
    assert res.status_code == 201
    assert res.json["storage"]["storage_type"] == "s3"
    storage_id = res.json["storage"]["storage_id"]

    _, res = await storage_test_client.delete(
        f"/api/data/storage/{storage_id}",
        headers=admin_headers,
    )
    assert res.status_code == 204

    _, res = await storage_test_client.get(
        f"/api/data/storage/{storage_id}",
        headers=admin_headers,
    )

    assert res.status_code == 404


@pytest.mark.asyncio
async def test_storage_deletion_unauthorized(storage_test_client, valid_storage_payload, admin_headers) -> None:
    storage_test_client, gl_auth = storage_test_client
    _, res = await storage_test_client.post(
        "/api/data/storage",
        headers=admin_headers,
        data=json.dumps(valid_storage_payload),
    )
    assert res.status_code == 201
    assert res.json["storage"]["storage_type"] == "s3"
    storage_id = res.json["storage"]["storage_id"]
    _, res = await storage_test_client.delete(
        f"/api/data/storage/{storage_id}",
        headers={"Authorization": ""},
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_storage_put(storage_test_client, valid_storage_payload, admin_headers) -> None:
    storage_test_client, _ = storage_test_client
    _, res = await storage_test_client.post(
        "/api/data/storage",
        headers=admin_headers,
        data=json.dumps(valid_storage_payload),
    )
    assert res.status_code == 201
    assert res.json["storage"]["storage_type"] == "s3"
    storage_id = res.json["storage"]["storage_id"]

    _, res = await storage_test_client.put(
        f"/api/data/storage/{storage_id}",
        headers=admin_headers,
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
async def test_storage_put_unauthorized(storage_test_client, valid_storage_payload, admin_headers) -> None:
    storage_test_client, gl_auth = storage_test_client
    _, res = await storage_test_client.post(
        "/api/data/storage",
        headers=admin_headers,
        data=json.dumps(valid_storage_payload),
    )
    assert res.status_code == 201
    assert res.json["storage"]["storage_type"] == "s3"
    storage_id = res.json["storage"]["storage_id"]
    _, res = await storage_test_client.put(
        f"/api/data/storage/{storage_id}",
        headers={"Authorization": ""},
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
    assert res.status_code == 403, res.text


@pytest.mark.asyncio
async def test_storage_patch(storage_test_client, valid_storage_payload) -> None:
    storage_test_client, _ = storage_test_client
    # NOTE: The keycloak dummy client used to authorize the storage patch requests only has info
    # on a user with name Admin Doe, using a different user will fail with a 401 error.
    access_token = json.dumps({"is_admin": False, "id": "some-id", "full_name": "Admin Doe"})
    _, res = await storage_test_client.post(
        "/api/data/storage",
        headers={"Authorization": f"bearer {access_token}"},
        data=json.dumps(valid_storage_payload),
    )
    assert res.status_code == 201
    assert res.json["storage"]["storage_type"] == "s3"
    storage_id = res.json["storage"]["storage_id"]

    _, res = await storage_test_client.patch(
        f"/api/data/storage/{storage_id}",
        headers={"Authorization": f"bearer {access_token}"},
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
        headers={"Authorization": f"bearer {access_token}"},
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
async def test_storage_patch_unauthorized(storage_test_client, valid_storage_payload, admin_headers) -> None:
    storage_test_client, gl_auth = storage_test_client
    _, res = await storage_test_client.post(
        "/api/data/storage",
        headers=admin_headers,
        data=json.dumps(valid_storage_payload),
    )
    assert res.status_code == 201
    assert res.json["storage"]["storage_type"] == "s3"
    storage_id = res.json["storage"]["storage_id"]
    _, res = await storage_test_client.patch(
        f"/api/data/storage/{storage_id}",
        headers={"Authorization": ""},
        data=json.dumps(
            {
                "configuration": {"type": "azureblob"},
                "source_path": "bucket/myotherfolder",
            }
        ),
    )
    assert res.status_code == 403, res.text


@pytest.mark.asyncio
async def test_storage_patch_banned_option(storage_test_client, valid_storage_payload) -> None:
    storage_test_client, _ = storage_test_client
    # NOTE: The keycloak dummy client used to authorize the storage patch requests only has info
    # on a user with name Admin Doe, using a different user will fail with a 401 error.
    access_token = json.dumps({"is_admin": False, "id": "some-id", "full_name": "Admin Doe"})
    payload = dict(valid_storage_payload)
    payload["configuration"] = {
        "type": "sftp",
        "host": "myhost",
    }
    _, res = await storage_test_client.post(
        "/api/data/storage",
        headers={"Authorization": f"bearer {access_token}"},
        data=json.dumps(payload),
    )
    assert res.status_code == 201
    assert res.json["storage"]["storage_type"] == "sftp"
    storage_id = res.json["storage"]["storage_id"]

    _, res = await storage_test_client.patch(
        f"/api/data/storage/{storage_id}",
        headers={"Authorization": f"bearer {access_token}"},
        data=json.dumps(
            {
                "configuration": {"key_file": "my_key"},
            }
        ),
    )
    assert res.status_code == 422
    assert "key_file option is not allowed" in res.text


@pytest.mark.asyncio
async def test_storage_obscure(storage_test_client) -> None:
    storage_test_client, _ = storage_test_client
    body = {
        "configuration": {
            "type": "seafile",
            "provider": "Other",
            "user": "abcdefg",
            "pass": "123456",
        }
    }
    _, res = await storage_test_client.post("/api/data/storage_schema/obscure", data=json.dumps(body))
    assert res.status_code == 200
    assert res.json["type"] == "seafile"
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

    body = {"configuration": {"type": "s3", "provider": "AWS"}, "source_path": "doesntexistatall/"}
    _, res = await storage_test_client.post("/api/data/storage_schema/test_connection", data=json.dumps(body))
    assert res.status_code == 422

    body = {"configuration": {"type": "s3", "provider": "AWS"}, "source_path": "giab/"}
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
    assert all(s["prefix"] not in BANNED_STORAGE for s in schema)

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

    # assert oauth is disabled for all providers
    oauth_providers = [s for s in schema if s["prefix"] in OAUTH_PROVIDERS]
    assert all(o["name"] != "client_id" and o["name"] != "client_secret" for p in oauth_providers for o in p["options"])

    # check the OAUTH_PROVIDERS list
    not_exists = set(p for p in OAUTH_PROVIDERS if p not in set(s["prefix"] for s in schema))
    assert not_exists == set()

    # check custom webdav storage is added
    assert any(s["prefix"] == "polybox" for s in schema)
    assert any(s["prefix"] == "switchDrive" for s in schema)

    # check that unsafe SFTP options are removed
    sftp = next((e for e in schema if e["prefix"] == "sftp"), None)
    assert sftp
    assert all(o["name"] not in BANNED_SFTP_OPTIONS for o in sftp["options"])

    # snapshot the schema
    assert schema == snapshot


@pytest.mark.asyncio
async def test_storage_validate_connection_supports_doi(storage_test_client) -> None:
    storage_test_client, _ = storage_test_client
    payload = {"configuration": {"type": "doi", "doi": "10.5281/zenodo.15174623"}, "source_path": ""}
    _, res = await storage_test_client.post("/api/data/storage_schema/test_connection", json=payload)
    assert res.status_code == 204, res.text
