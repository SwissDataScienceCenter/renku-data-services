import json
from typing import Any

import pytest
import pytest_asyncio
from sanic import Sanic
from sanic_testing.testing import SanicASGITestClient
from ulid import ULID

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


def merge_headers(*headers: dict[str, str]) -> dict[str, str]:
    """Merge multiple headers."""
    all_headers = dict()
    for h in headers:
        all_headers.update(**h)
    return all_headers


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


@pytest.mark.asyncio
async def test_post_storage_success(
    sanic_client: SanicASGITestClient,
    create_project,
    admin_headers: dict[str, str],
    user_headers: dict[str, str],
) -> None:
    project = await create_project(sanic_client, "Test Project")
    namespace = f"{project['namespace']}/{project['slug']}"
    project_id = project["id"]

    payload = {"project_ref": {"id": project_id}, "max_size": 10}
    _, response = await sanic_client.post("/api/data/storage/allow", headers=admin_headers, json=payload)
    assert response.status_code == 201, response.text

    payload = {"namespace": namespace, "size": 10, "mount_path": "/data"}
    _, response = await sanic_client.post("/api/data/storage", headers=user_headers, json=payload)

    assert response.status_code == 201, response.text
    assert response.json is not None
    storage = response.json
    assert storage.get("project_id") == project["id"]
    assert storage.get("size") == 10
    assert storage.get("mount_path") == "/data"
    assert storage.get("created_by") == "user"
    assert "ETag" in response.headers


@pytest.mark.asyncio
async def test_post_storage_unauthenticated_fails(
    sanic_client: SanicASGITestClient, create_project, admin_headers: dict[str, str]
) -> None:
    project = await create_project(sanic_client, "Test Project")
    namespace = f"{project['namespace']}/{project['slug']}"

    project_id = project["id"]
    payload = {"project_ref": {"id": project_id}, "max_size": 10}
    _, response = await sanic_client.post("/api/data/storage/allow", headers=admin_headers, json=payload)
    assert response.status_code == 201, response.text

    payload = {"namespace": namespace, "size": 10, "mount_path": "/data"}
    _, response = await sanic_client.post("/api/data/storage", json=payload)

    assert response.status_code == 401, response.text


@pytest.mark.asyncio
async def test_post_storage_not_allowed_fails(
    sanic_client: SanicASGITestClient, create_project, user_headers: dict[str, str]
) -> None:
    project = await create_project(sanic_client, "Test Project")
    namespace = f"{project['namespace']}/{project['slug']}"

    payload = {"namespace": namespace, "size": 10, "mount_path": "/data"}
    _, response = await sanic_client.post("/api/data/storage", json=payload, headers=user_headers)

    assert response.status_code == 403, response.text


@pytest.mark.asyncio
async def test_post_storage_duplicate_fails(
    sanic_client: SanicASGITestClient, create_project, user_headers: dict[str, str], admin_headers: dict[str, str]
) -> None:
    project = await create_project(sanic_client, "Test Project")
    namespace = f"{project['namespace']}/{project['slug']}"

    project_id = project["id"]
    payload = {"project_ref": {"id": project_id}, "max_size": 10}
    _, response = await sanic_client.post("/api/data/storage/allow", headers=admin_headers, json=payload)
    assert response.status == 201

    payload = {"namespace": namespace, "size": 10, "mount_path": "/data"}
    _, response = await sanic_client.post("/api/data/storage", headers=user_headers, json=payload)
    assert response.status_code == 201, response.text

    _, response = await sanic_client.post("/api/data/storage", headers=user_headers, json=payload)

    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_get_one_storage_success(
    sanic_client: SanicASGITestClient, create_project, user_headers: dict[str, str], admin_headers: dict[str, str]
) -> None:
    project = await create_project(sanic_client, "Test Project")
    namespace = f"{project['namespace']}/{project['slug']}"

    project_id = project["id"]
    payload = {"project_ref": {"id": project_id}, "max_size": 10}
    _, response = await sanic_client.post("/api/data/storage/allow", headers=admin_headers, json=payload)
    assert response.status_code == 201, response.text

    payload = {"namespace": namespace, "size": 10, "mount_path": "/data"}
    _, response = await sanic_client.post("/api/data/storage", headers=user_headers, json=payload)
    assert response.status_code == 201, response.text
    storage_id = response.json["id"]

    _, response = await sanic_client.get(f"/api/data/storage/{storage_id}", headers=user_headers)

    assert response.status_code == 200, response.text
    assert response.json is not None
    storage = response.json
    assert storage.get("id") == storage_id
    assert storage.get("project_id") == project["id"]
    assert storage.get("size") == 10
    assert storage.get("mount_path") == "/data"


@pytest.mark.asyncio
async def test_get_one_storage_not_found(sanic_client: SanicASGITestClient, user_headers: dict[str, str]) -> None:
    non_existent_id = str(ULID())
    _, response = await sanic_client.get(f"/api/data/storage/{non_existent_id}", headers=user_headers)

    assert response.status_code == 404, response.text


@pytest.mark.asyncio
async def test_get_one_storage_etag(
    sanic_client: SanicASGITestClient, create_project, user_headers: dict[str, str], admin_headers: dict[str, str]
) -> None:
    project = await create_project(sanic_client, "Test Project")
    namespace = f"{project['namespace']}/{project['slug']}"

    project_id = project["id"]
    payload = {"project_ref": {"id": project_id}, "max_size": 10}
    _, response = await sanic_client.post("/api/data/storage/allow", headers=admin_headers, json=payload)
    assert response.status_code == 201, response.text

    payload = {"namespace": namespace, "size": 10, "mount_path": "/data"}
    _, response = await sanic_client.post("/api/data/storage", headers=user_headers, json=payload)
    assert response.status_code == 201, response.text
    storage_id = response.json["id"]
    etag = response.headers["ETag"]

    headers = merge_headers(user_headers, {"If-None-Match": etag})
    _, response = await sanic_client.get(f"/api/data/storage/{storage_id}", headers=headers)

    assert response.status_code == 304, response.text


@pytest.mark.asyncio
async def test_get_storage_to_project_for_no_storage(
    sanic_client: SanicASGITestClient, create_project, user_headers: dict[str, str]
) -> None:
    project = await create_project(sanic_client, "Test Project")

    _, response = await sanic_client.get(f"/api/data/projects/{project['id']}/storage", headers=user_headers)

    assert response.status_code == 200, response.text
    assert response.json == []


@pytest.mark.asyncio
async def test_get_storage_to_project_success(
    sanic_client: SanicASGITestClient, create_project, user_headers: dict[str, str], admin_headers: dict[str, str]
) -> None:
    project = await create_project(sanic_client, "Test Project")
    namespace = f"{project['namespace']}/{project['slug']}"

    project_id = project["id"]
    payload = {"project_ref": {"id": project_id}, "max_size": 10}
    _, response = await sanic_client.post("/api/data/storage/allow", headers=admin_headers, json=payload)
    assert response.status == 201

    payload = {"namespace": namespace, "size": 10, "mount_path": "/data"}
    _, response = await sanic_client.post("/api/data/storage", headers=user_headers, json=payload)
    assert response.status_code == 201, response.text

    _, response = await sanic_client.get(f"/api/data/projects/{project['id']}/storage", headers=user_headers)

    assert response.status_code == 200, response.text
    assert len(response.json) == 1
    storage = response.json[0]
    assert storage.get("project_id") == project["id"]
    assert storage.get("size") == 10
    assert storage.get("mount_path") == "/data"


@pytest.mark.asyncio
async def test_delete_storage_success(
    sanic_client: SanicASGITestClient,
    create_project,
    user_headers: dict[str, str],
    admin_headers: dict[str, str],
    cluster,
) -> None:
    project = await create_project(sanic_client, "Test Project")
    namespace = f"{project['namespace']}/{project['slug']}"

    project_id = project["id"]
    payload = {"project_ref": {"id": project_id}, "max_size": 10}
    _, response = await sanic_client.post("/api/data/storage/allow", headers=admin_headers, json=payload)
    assert response.status_code == 201, response.text

    payload = {"namespace": namespace, "size": 10, "mount_path": "/data"}
    _, response = await sanic_client.post("/api/data/storage", headers=user_headers, json=payload)
    assert response.status_code == 201, response.text
    storage_id = response.json["id"]

    _, response = await sanic_client.delete(f"/api/data/storage/{storage_id}", headers=user_headers)
    assert response.status_code == 204, response.text

    _, response = await sanic_client.get(f"/api/data/projects/{project['id']}/storage", headers=user_headers)
    assert response.status_code == 200, response.text
    assert response.json == []


@pytest.mark.asyncio
async def test_delete_storage_unauthenticated_fails(
    sanic_client: SanicASGITestClient, create_project, user_headers: dict[str, str], admin_headers: dict[str, str]
) -> None:
    project = await create_project(sanic_client, "Test Project")
    namespace = f"{project['namespace']}/{project['slug']}"

    project_id = project["id"]
    payload = {"project_ref": {"id": project_id}, "max_size": 10}
    _, response = await sanic_client.post("/api/data/storage/allow", headers=admin_headers, json=payload)
    assert response.status_code == 201, response.text

    payload = {"namespace": namespace, "size": 10, "mount_path": "/data"}
    _, response = await sanic_client.post("/api/data/storage", headers=user_headers, json=payload)
    assert response.status_code == 201, response.text
    storage_id = response.json["id"]

    _, response = await sanic_client.delete(f"/api/data/storage/{storage_id}")

    assert response.status_code == 401, response.text


@pytest.mark.asyncio
async def test_post_storage_allow_success(
    sanic_client: SanicASGITestClient, create_project, admin_headers: dict[str, str]
) -> None:
    project = await create_project(sanic_client, "Test Project")
    project_id = project["id"]

    payload = {"project_ref": {"id": project_id}, "max_size": 10}
    _, response = await sanic_client.post("/api/data/storage/allow", headers=admin_headers, json=payload)

    assert response.status_code == 201, response.text
    assert response.json is not None
    allow = response.json
    assert allow.get("project_ref").get("id") == project_id
    assert allow.get("max_size") == 10


@pytest.mark.asyncio
async def test_post_storage_allow_requires_admin(
    sanic_client: SanicASGITestClient, create_project, user_headers: dict[str, str]
) -> None:
    project = await create_project(sanic_client, "Test Project")

    payload = {"project_ref": {"id": project["id"]}, "max_size": 10}
    _, response = await sanic_client.post("/api/data/storage/allow", headers=user_headers, json=payload)

    assert response.status_code == 403, response.text


@pytest.mark.asyncio
async def test_post_storage_allow_unauthenticated_fails(
    sanic_client: SanicASGITestClient, create_project, user_headers: dict[str, str]
) -> None:
    project = await create_project(sanic_client, "Test Project")

    payload = {"project_ref": {"id": project["id"]}, "max_size": 10}
    _, response = await sanic_client.post("/api/data/storage/allow", json=payload)

    assert response.status_code == 401, response.text


@pytest.mark.asyncio
async def test_post_storage_allow_duplicate_fails(
    sanic_client: SanicASGITestClient, create_project, admin_headers: dict[str, str]
) -> None:
    project = await create_project(sanic_client, "Test Project")
    project_id = project["id"]

    payload = {"project_ref": {"id": project_id}, "max_size": 10}
    _, response = await sanic_client.post("/api/data/storage/allow", headers=admin_headers, json=payload)
    assert response.status_code == 201, response.text

    _, response = await sanic_client.post("/api/data/storage/allow", headers=admin_headers, json=payload)

    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_delete_storage_allow_success(
    sanic_client: SanicASGITestClient, create_project, admin_headers: dict[str, str]
) -> None:
    project = await create_project(sanic_client, "Test Project")
    project_id = project["id"]

    payload = {"project_ref": {"id": project_id}, "max_size": 10}
    _, response = await sanic_client.post("/api/data/storage/allow", headers=admin_headers, json=payload)
    assert response.status_code == 201, response.text

    _, response = await sanic_client.delete(f"/api/data/storage/allow/{project_id}", headers=admin_headers)

    assert response.status_code == 204, response.text

    # Re-adding after deletion should succeed
    _, response = await sanic_client.post("/api/data/storage/allow", headers=admin_headers, json=payload)
    assert response.status_code == 201, response.text


@pytest.mark.asyncio
async def test_delete_storage_allow_requires_admin(
    sanic_client: SanicASGITestClient, create_project, admin_headers: dict[str, str], user_headers: dict[str, str]
) -> None:
    project = await create_project(sanic_client, "Test Project")
    project_id = project["id"]

    payload = {"project_ref": {"id": project_id}, "max_size": 10}
    _, response = await sanic_client.post("/api/data/storage/allow", headers=admin_headers, json=payload)
    assert response.status_code == 201, response.text

    _, response = await sanic_client.delete(f"/api/data/storage/allow/{project_id}", headers=user_headers)

    assert response.status_code == 403, response.text


@pytest.mark.asyncio
async def test_get_storage_allow_success(
    sanic_client: SanicASGITestClient, create_project, admin_headers: dict[str, str], user_headers: dict[str, str]
) -> None:
    project = await create_project(sanic_client, "Test Project")
    project_id = project["id"]

    payload = {"project_ref": {"id": project_id}, "max_size": 10}
    _, response = await sanic_client.post("/api/data/storage/allow", headers=admin_headers, json=payload)
    assert response.status_code == 201, response.text

    _, response = await sanic_client.get(f"/api/data/storage/allow/{project_id}", headers=user_headers)

    assert response.status_code == 200, response.text
    assert response.json is not None
    assert response.json.get("project_id") == project_id
    assert response.json.get("max_size") == 10


@pytest.mark.asyncio
async def test_get_storage_allow_not_in_list(
    sanic_client: SanicASGITestClient, create_project, user_headers: dict[str, str]
) -> None:
    project = await create_project(sanic_client, "Test Project")
    project_id = project["id"]

    _, response = await sanic_client.get(f"/api/data/storage/allow/{project_id}", headers=user_headers)

    assert response.status_code == 404, response.text


@pytest.mark.asyncio
async def test_get_storage_allow_unauthenticated(
    sanic_client: SanicASGITestClient, create_project, admin_headers: dict[str, str]
) -> None:
    project = await create_project(sanic_client, "Test Project")
    project_id = project["id"]

    payload = {"project_ref": {"id": project_id}, "max_size": 10}
    _, response = await sanic_client.post("/api/data/storage/allow", headers=admin_headers, json=payload)
    assert response.status_code == 201, response.text

    _, response = await sanic_client.get(f"/api/data/storage/allow/{project_id}")

    assert response.status_code == 401, response.text


@pytest.mark.asyncio
async def test_patch_storage_success(
    sanic_client: SanicASGITestClient,
    create_project,
    user_headers: dict[str, str],
    admin_headers: dict[str, str],
) -> None:
    project = await create_project(sanic_client, "Test Project")
    namespace = f"{project['namespace']}/{project['slug']}"

    project_id = project["id"]
    payload = {"project_ref": {"id": project_id}, "max_size": 10}
    _, response = await sanic_client.post("/api/data/storage/allow", headers=admin_headers, json=payload)
    assert response.status_code == 201, response.text

    payload = {"namespace": namespace, "size": 5, "mount_path": "/data"}
    _, response = await sanic_client.post("/api/data/storage", headers=user_headers, json=payload)
    assert response.status_code == 201, response.text
    storage = response.json
    storage_id = storage["id"]
    original_etag = response.headers["ETag"]

    # Patch the size
    headers = merge_headers(user_headers, {"If-Match": original_etag})
    patch = {"size": 8}
    _, response = await sanic_client.patch(f"/api/data/storage/{storage_id}", headers=headers, json=patch)

    assert response.status_code == 200, response.text
    assert response.json is not None
    updated_storage = response.json
    assert updated_storage.get("id") == storage_id
    assert updated_storage.get("size") == 8
    assert updated_storage.get("mount_path") == "/data"


@pytest.mark.asyncio
async def test_patch_storage_mount_path(
    sanic_client: SanicASGITestClient, create_project, user_headers: dict[str, str], admin_headers: dict[str, str]
) -> None:
    project = await create_project(sanic_client, "Test Project")
    namespace = f"{project['namespace']}/{project['slug']}"

    project_id = project["id"]
    payload = {"project_ref": {"id": project_id}, "max_size": 10}
    _, response = await sanic_client.post("/api/data/storage/allow", headers=admin_headers, json=payload)
    assert response.status_code == 201, response.text

    payload = {"namespace": namespace, "size": 10, "mount_path": "/data"}
    _, response = await sanic_client.post("/api/data/storage", headers=user_headers, json=payload)
    assert response.status_code == 201, response.text
    storage = response.json
    storage_id = storage["id"]

    # Patch the mount path
    headers = merge_headers(user_headers, {"If-Match": response.headers["ETag"]})
    patch = {"mount_path": "/new/mount"}
    _, response = await sanic_client.patch(f"/api/data/storage/{storage_id}", headers=headers, json=patch)

    assert response.status_code == 200, response.text
    assert response.json is not None
    updated_storage = response.json
    assert updated_storage.get("id") == storage_id
    assert updated_storage.get("size") == 10
    assert updated_storage.get("mount_path") == "/new/mount"


@pytest.mark.asyncio
async def test_patch_storage_both_fields(
    sanic_client: SanicASGITestClient, create_project, user_headers: dict[str, str], admin_headers: dict[str, str]
) -> None:
    project = await create_project(sanic_client, "Test Project")
    namespace = f"{project['namespace']}/{project['slug']}"

    project_id = project["id"]
    payload = {"project_ref": {"id": project_id}, "max_size": 10}
    _, response = await sanic_client.post("/api/data/storage/allow", headers=admin_headers, json=payload)
    assert response.status_code == 201, response.text

    payload = {"namespace": namespace, "size": 5, "mount_path": "/data"}
    _, response = await sanic_client.post("/api/data/storage", headers=user_headers, json=payload)
    assert response.status_code == 201, response.text
    storage = response.json
    storage_id = storage["id"]

    # Patch both fields at once
    headers = merge_headers(user_headers, {"If-Match": response.headers["ETag"]})
    patch = {"size": 8, "mount_path": "/new/mount"}
    _, response = await sanic_client.patch(f"/api/data/storage/{storage_id}", headers=headers, json=patch)

    assert response.status_code == 200, response.text
    assert response.json is not None
    updated_storage = response.json
    assert updated_storage.get("id") == storage_id
    assert updated_storage.get("size") == 8
    assert updated_storage.get("mount_path") == "/new/mount"


@pytest.mark.asyncio
async def test_patch_storage_without_if_match_header(
    sanic_client: SanicASGITestClient, create_project, user_headers: dict[str, str], admin_headers: dict[str, str]
) -> None:
    project = await create_project(sanic_client, "Test Project")
    namespace = f"{project['namespace']}/{project['slug']}"

    project_id = project["id"]
    payload = {"project_ref": {"id": project_id}, "max_size": 10}
    _, response = await sanic_client.post("/api/data/storage/allow", headers=admin_headers, json=payload)
    assert response.status_code == 201, response.text

    payload = {"namespace": namespace, "size": 10, "mount_path": "/data"}
    _, response = await sanic_client.post("/api/data/storage", headers=user_headers, json=payload)
    assert response.status_code == 201, response.text
    storage_id = response.json["id"]

    # Patch without If-Match header
    patch = {"size": 20}
    _, response = await sanic_client.patch(f"/api/data/storage/{storage_id}", headers=user_headers, json=patch)

    assert response.status_code == 428, response.text
    assert "If-Match header not provided" in response.text


@pytest.mark.asyncio
async def test_patch_storage_with_invalid_etag(
    sanic_client: SanicASGITestClient, create_project, user_headers: dict[str, str], admin_headers: dict[str, str]
) -> None:
    project = await create_project(sanic_client, "Test Project")
    namespace = f"{project['namespace']}/{project['slug']}"

    project_id = project["id"]
    payload = {"project_ref": {"id": project_id}, "max_size": 10}
    _, response = await sanic_client.post("/api/data/storage/allow", headers=admin_headers, json=payload)
    assert response.status_code == 201, response.text

    payload = {"namespace": namespace, "size": 5, "mount_path": "/data"}
    _, response = await sanic_client.post("/api/data/storage", headers=user_headers, json=payload)
    assert response.status_code == 201, response.text
    storage_id = response.json["id"]
    correct_etag = response.headers["ETag"]

    # Patch with wrong ETag
    headers = merge_headers(user_headers, {"If-Match": "wrong-etag"})
    patch = {"size": 8}
    _, response = await sanic_client.patch(f"/api/data/storage/{storage_id}", headers=headers, json=patch)

    assert response.status_code == 409, response.text

    # Verify the etag changed after a successful patch
    headers = merge_headers(user_headers, {"If-Match": correct_etag})
    patch = {"size": 6}
    _, response = await sanic_client.patch(f"/api/data/storage/{storage_id}", headers=headers, json=patch)
    assert response.status_code == 200, response.text
    new_etag = response.headers["ETag"]
    assert new_etag != correct_etag


@pytest.mark.asyncio
async def test_patch_storage_not_found(sanic_client: SanicASGITestClient, user_headers: dict[str, str]) -> None:
    non_existent_id = str(ULID())
    headers = merge_headers(user_headers, {"If-Match": "some-etag"})
    patch = {"size": 20}
    _, response = await sanic_client.patch(f"/api/data/storage/{non_existent_id}", headers=headers, json=patch)

    assert response.status_code == 404, response.text


@pytest.mark.asyncio
async def test_patch_storage_unauthenticated_fails(
    sanic_client: SanicASGITestClient, create_project, admin_headers: dict[str, str], user_headers: dict[str, str]
) -> None:
    project = await create_project(sanic_client, "Test Project")
    namespace = f"{project['namespace']}/{project['slug']}"

    project_id = project["id"]
    payload = {"project_ref": {"id": project_id}, "max_size": 10}
    _, response = await sanic_client.post("/api/data/storage/allow", headers=admin_headers, json=payload)
    assert response.status_code == 201, response.text

    payload = {"namespace": namespace, "size": 5, "mount_path": "/data"}
    _, response = await sanic_client.post("/api/data/storage", headers=user_headers, json=payload)
    assert response.status_code == 201, response.text
    storage_id = response.json["id"]

    # Patch without authentication
    _, response = await sanic_client.patch(f"/api/data/storage/{storage_id}", json={"size": 8})

    assert response.status_code == 401, response.text


@pytest.mark.asyncio
async def test_patch_storage_exceeds_max_size(
    sanic_client: SanicASGITestClient, create_project, user_headers: dict[str, str], admin_headers: dict[str, str]
) -> None:
    project = await create_project(sanic_client, "Test Project")
    namespace = f"{project['namespace']}/{project['slug']}"

    project_id = project["id"]
    payload = {"project_ref": {"id": project_id}, "max_size": 10}
    _, response = await sanic_client.post("/api/data/storage/allow", headers=admin_headers, json=payload)
    assert response.status_code == 201, response.text

    payload = {"namespace": namespace, "size": 5, "mount_path": "/data"}
    _, response = await sanic_client.post("/api/data/storage", headers=user_headers, json=payload)
    assert response.status_code == 201, response.text
    storage_id = response.json["id"]

    # Try to patch size beyond the allowed max (10GB)
    headers = merge_headers(user_headers, {"If-Match": response.headers["ETag"]})
    patch = {"size": 11}
    _, response = await sanic_client.patch(f"/api/data/storage/{storage_id}", headers=headers, json=patch)

    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_patch_storage_invalid_mount_path(
    sanic_client: SanicASGITestClient, create_project, user_headers: dict[str, str], admin_headers: dict[str, str]
) -> None:
    project = await create_project(sanic_client, "Test Project")
    namespace = f"{project['namespace']}/{project['slug']}"

    project_id = project["id"]
    payload = {"project_ref": {"id": project_id}, "max_size": 10}
    _, response = await sanic_client.post("/api/data/storage/allow", headers=admin_headers, json=payload)
    assert response.status_code == 201, response.text

    payload = {"namespace": namespace, "size": 10, "mount_path": "/data"}
    _, response = await sanic_client.post("/api/data/storage", headers=user_headers, json=payload)
    assert response.status_code == 201, response.text
    storage_id = response.json["id"]

    # Try to patch with invalid mount path
    headers = merge_headers(user_headers, {"If-Match": response.headers["ETag"]})
    patch = {"mount_path": "/etc/passwd"}
    _, response = await sanic_client.patch(f"/api/data/storage/{storage_id}", headers=headers, json=patch)

    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_patch_storage_allow_success(
    sanic_client: SanicASGITestClient, create_project, admin_headers: dict[str, str], user_headers: dict[str, str]
) -> None:
    project = await create_project(sanic_client, "Test Project")
    project_id = project["id"]

    payload = {"project_ref": {"id": project_id}, "max_size": 10}
    _, response = await sanic_client.post("/api/data/storage/allow", headers=admin_headers, json=payload)
    assert response.status_code == 201, response.text

    # Get the allow entry to retrieve the etag (use user_headers as admin may not have read access)
    _, response = await sanic_client.get(f"/api/data/storage/allow/{project_id}", headers=user_headers)
    assert response.status_code == 200, response.text
    etag = response.headers["ETag"]

    # Patch the max_size
    headers = merge_headers(admin_headers, {"If-Match": etag})
    patch = {"max_size": 20}
    _, response = await sanic_client.patch(f"/api/data/storage/allow/{project_id}", headers=headers, json=patch)

    assert response.status_code == 200, response.text
    assert response.json is not None
    updated_allow = response.json
    assert updated_allow.get("project_id") == project_id
    assert updated_allow.get("max_size") == 20


@pytest.mark.asyncio
async def test_patch_storage_allow_requires_admin(
    sanic_client: SanicASGITestClient, create_project, admin_headers: dict[str, str], user_headers: dict[str, str]
) -> None:
    project = await create_project(sanic_client, "Test Project")
    project_id = project["id"]

    payload = {"project_ref": {"id": project_id}, "max_size": 10}
    _, response = await sanic_client.post("/api/data/storage/allow", headers=admin_headers, json=payload)
    assert response.status_code == 201, response.text

    # Get the allow entry to retrieve the etag (use user_headers as admin may not have read access)
    _, response = await sanic_client.get(f"/api/data/storage/allow/{project_id}", headers=admin_headers)
    assert response.status_code == 200, response.text
    etag = response.headers["ETag"]

    # Try to patch as non-admin
    headers = merge_headers(user_headers, {"If-Match": etag})
    patch = {"max_size": 20}
    _, response = await sanic_client.patch(f"/api/data/storage/allow/{project_id}", headers=headers, json=patch)

    assert response.status_code == 403, response.text


@pytest.mark.asyncio
async def test_patch_storage_allow_without_if_match_header(
    sanic_client: SanicASGITestClient, create_project, admin_headers: dict[str, str]
) -> None:
    project = await create_project(sanic_client, "Test Project")
    project_id = project["id"]

    payload = {"project_ref": {"id": project_id}, "max_size": 10}
    _, response = await sanic_client.post("/api/data/storage/allow", headers=admin_headers, json=payload)
    assert response.status_code == 201, response.text

    # Patch without If-Match header
    patch = {"max_size": 20}
    _, response = await sanic_client.patch(f"/api/data/storage/allow/{project_id}", headers=admin_headers, json=patch)

    assert response.status_code == 428, response.text
    assert "If-Match header not provided" in response.text


@pytest.mark.asyncio
async def test_patch_storage_allow_with_invalid_etag(
    sanic_client: SanicASGITestClient, create_project, admin_headers: dict[str, str], user_headers: dict[str, str]
) -> None:
    project = await create_project(sanic_client, "Test Project")
    project_id = project["id"]

    payload = {"project_ref": {"id": project_id}, "max_size": 10}
    _, response = await sanic_client.post("/api/data/storage/allow", headers=admin_headers, json=payload)
    assert response.status_code == 201, response.text

    # Get the allow entry to retrieve the etag (use user_headers as admin may not have read access)
    _, response = await sanic_client.get(f"/api/data/storage/allow/{project_id}", headers=user_headers)
    assert response.status_code == 200, response.text
    correct_etag = response.headers["ETag"]

    # Patch with wrong ETag
    headers = merge_headers(admin_headers, {"If-Match": "wrong-etag"})
    patch = {"max_size": 20}
    _, response = await sanic_client.patch(f"/api/data/storage/allow/{project_id}", headers=headers, json=patch)

    assert response.status_code == 409, response.text

    # Verify the etag changed after a successful patch
    headers = merge_headers(admin_headers, {"If-Match": correct_etag})
    patch = {"max_size": 15}
    _, response = await sanic_client.patch(f"/api/data/storage/allow/{project_id}", headers=headers, json=patch)
    assert response.status_code == 200, response.text
    new_etag = response.headers["ETag"]
    assert new_etag != correct_etag


@pytest.mark.asyncio
async def test_patch_storage_allow_not_in_list(
    sanic_client: SanicASGITestClient, create_project, admin_headers: dict[str, str]
) -> None:
    project = await create_project(sanic_client, "Test Project")
    project_id = project["id"]

    headers = merge_headers(admin_headers, {"If-Match": "some-etag"})
    patch = {"max_size": 20}
    _, response = await sanic_client.patch(f"/api/data/storage/allow/{project_id}", headers=headers, json=patch)

    assert response.status_code == 404, response.text


@pytest.mark.asyncio
async def test_patch_storage_allow_unauthenticated_fails(
    sanic_client: SanicASGITestClient, create_project, admin_headers: dict[str, str]
) -> None:
    project = await create_project(sanic_client, "Test Project")
    project_id = project["id"]

    payload = {"project_ref": {"id": project_id}, "max_size": 10}
    _, response = await sanic_client.post("/api/data/storage/allow", headers=admin_headers, json=payload)
    assert response.status_code == 201, response.text

    # Patch without authentication
    _, response = await sanic_client.patch(f"/api/data/storage/allow/{project_id}", json={"max_size": 20})

    assert response.status_code == 401, response.text


@pytest.mark.asyncio
async def test_patch_storage_allow_min_size(
    sanic_client: SanicASGITestClient, create_project, admin_headers: dict[str, str], user_headers: dict[str, str]
) -> None:
    project = await create_project(sanic_client, "Test Project")
    project_id = project["id"]

    payload = {"project_ref": {"id": project_id}, "max_size": 10}
    _, response = await sanic_client.post("/api/data/storage/allow", headers=admin_headers, json=payload)
    assert response.status_code == 201, response.text

    # Get the allow entry to retrieve the etag (use user_headers as admin may not have read access)
    _, response = await sanic_client.get(f"/api/data/storage/allow/{project_id}", headers=user_headers)
    assert response.status_code == 200, response.text
    etag = response.headers["ETag"]

    # Try to set max_size below minimum (1GB)
    headers = merge_headers(admin_headers, {"If-Match": etag})
    patch = {"max_size": 0}
    _, response = await sanic_client.patch(f"/api/data/storage/allow/{project_id}", headers=headers, json=patch)

    assert response.status_code == 422, response.text
    assert "should be greater than 0" in response.text


@pytest.mark.asyncio
async def test_get_all_storage_allow(
    sanic_client: SanicASGITestClient, create_project, admin_headers: dict[str, str], user_headers: dict[str, str]
) -> None:
    project = await create_project(sanic_client, "Test Project")
    project_id = project["id"]
    slug = f"{project["namespace"]}/{project["slug"]}"

    payload = {"project_ref": {"slug": slug}, "max_size": 10}
    _, response = await sanic_client.post("/api/data/storage/allow", headers=admin_headers, json=payload)
    assert response.status_code == 201, response.text

    _, response = await sanic_client.get("/api/data/storage/allow", headers=admin_headers)
    assert response.status_code == 200, response.text
    assert response.json is not None, f"No json response body: {response.text}"
    assert isinstance(response.json, list)
    assert len(response.json) == 1
    assert response.json[0]["project_id"] == project_id
    assert response.json[0]["max_size"] == 10
