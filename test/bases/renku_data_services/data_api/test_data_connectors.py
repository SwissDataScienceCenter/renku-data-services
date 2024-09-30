from typing import Any

import pytest
from sanic_testing.testing import SanicASGITestClient

from test.bases.renku_data_services.data_api.utils import merge_headers


@pytest.fixture
def create_data_connector(sanic_client: SanicASGITestClient, regular_user, user_headers):
    async def create_data_connector_helper(name: str, **payload) -> dict[str, Any]:
        dc_payload = {
            "name": name,
            "description": "A data connector",
            "visibility": "public",
            "namespace": f"{regular_user.first_name}.{regular_user.last_name}",
            "storage": {
                "configuration": {
                    "type": "s3",
                    "provider": "AWS",
                    "region": "us-east-1",
                },
                "source_path": "bucket/my-folder",
                "target_path": "my/target",
            },
            "keywords": ["keyword 1", "keyword.2", "keyword-3", "KEYWORD_4"],
        }
        dc_payload.update(payload)

        _, response = await sanic_client.post("/api/data/data_connectors", headers=user_headers, json=dc_payload)

        assert response.status_code == 201, response.text
        return response.json

    return create_data_connector_helper


@pytest.mark.asyncio
async def test_post_data_connector(sanic_client: SanicASGITestClient, regular_user, user_headers) -> None:
    payload = {
        "name": "My data connector",
        "slug": "my-data-connector",
        "description": "A data connector",
        "visibility": "public",
        "namespace": f"{regular_user.first_name}.{regular_user.last_name}",
        "storage": {
            "configuration": {
                "type": "s3",
                "provider": "AWS",
                "region": "us-east-1",
            },
            "source_path": "bucket/my-folder",
            "target_path": "my/target",
        },
        "keywords": ["keyword 1", "keyword.2", "keyword-3", "KEYWORD_4"],
    }

    _, response = await sanic_client.post("/api/data/data_connectors", headers=user_headers, json=payload)

    assert response.status_code == 201, response.text
    assert response.json is not None
    data_connector = response.json
    assert data_connector.get("name") == "My data connector"
    assert data_connector.get("namespace") == "user.doe"
    assert data_connector.get("slug") == "my-data-connector"
    assert data_connector.get("storage") is not None
    storage = data_connector["storage"]
    assert storage.get("storage_type") == "s3"
    assert storage.get("source_path") == "bucket/my-folder"
    assert storage.get("target_path") == "my/target"
    assert storage.get("readonly") is True
    assert data_connector.get("created_by") == "user"
    assert data_connector.get("visibility") == "public"
    assert data_connector.get("description") == "A data connector"
    assert set(data_connector.get("keywords")) == {"keyword 1", "keyword.2", "keyword-3", "KEYWORD_4"}


@pytest.mark.asyncio
async def test_post_data_connector_with_s3_url(sanic_client: SanicASGITestClient, regular_user, user_headers) -> None:
    payload = {
        "name": "My data connector",
        "slug": "my-data-connector",
        "description": "A data connector",
        "visibility": "public",
        "namespace": f"{regular_user.first_name}.{regular_user.last_name}",
        "storage": {
            "storage_url": "s3://my-bucket",
            "target_path": "my/target",
        },
        "keywords": ["keyword 1", "keyword.2", "keyword-3", "KEYWORD_4"],
    }

    _, response = await sanic_client.post("/api/data/data_connectors", headers=user_headers, json=payload)

    assert response.status_code == 201, response.text
    assert response.json is not None
    data_connector = response.json
    assert data_connector.get("name") == "My data connector"
    assert data_connector.get("namespace") == "user.doe"
    assert data_connector.get("slug") == "my-data-connector"
    assert data_connector.get("storage") is not None
    storage = data_connector["storage"]
    assert storage.get("storage_type") == "s3"
    assert storage.get("source_path") == "my-bucket"
    assert storage.get("target_path") == "my/target"
    assert storage.get("readonly") is True
    assert data_connector.get("created_by") == "user"
    assert data_connector.get("visibility") == "public"
    assert data_connector.get("description") == "A data connector"
    assert set(data_connector.get("keywords")) == {"keyword 1", "keyword.2", "keyword-3", "KEYWORD_4"}


@pytest.mark.asyncio
async def test_post_data_connector_with_azure_url(
    sanic_client: SanicASGITestClient, regular_user, user_headers
) -> None:
    payload = {
        "name": "My data connector",
        "slug": "my-data-connector",
        "description": "A data connector",
        "visibility": "public",
        "namespace": f"{regular_user.first_name}.{regular_user.last_name}",
        "storage": {
            "storage_url": "azure://mycontainer/myfolder",
            "target_path": "my/target",
        },
        "keywords": ["keyword 1", "keyword.2", "keyword-3", "KEYWORD_4"],
    }

    _, response = await sanic_client.post("/api/data/data_connectors", headers=user_headers, json=payload)

    assert response.status_code == 201, response.text
    assert response.json is not None
    data_connector = response.json
    assert data_connector.get("name") == "My data connector"
    assert data_connector.get("namespace") == "user.doe"
    assert data_connector.get("slug") == "my-data-connector"
    assert data_connector.get("storage") is not None
    storage = data_connector["storage"]
    assert storage.get("storage_type") == "azureblob"
    assert storage.get("source_path") == "mycontainer/myfolder"
    assert storage.get("target_path") == "my/target"
    assert storage.get("readonly") is True
    assert data_connector.get("created_by") == "user"
    assert data_connector.get("visibility") == "public"
    assert data_connector.get("description") == "A data connector"
    assert set(data_connector.get("keywords")) == {"keyword 1", "keyword.2", "keyword-3", "KEYWORD_4"}


@pytest.mark.asyncio
async def test_get_all_data_connectors_pagination(
    sanic_client: SanicASGITestClient, create_data_connector, user_headers
) -> None:
    for i in range(1, 10):
        await create_data_connector(f"Data connector {i}")

    parameters = {"page": 2, "per_page": 3}
    _, response = await sanic_client.get("/api/data/data_connectors", headers=user_headers, params=parameters)

    assert response.status_code == 200, response.text
    assert response.json is not None
    data_connectors = response.json
    assert {dc["name"] for dc in data_connectors} == {
        "Data connector 4",
        "Data connector 5",
        "Data connector 6",
    }
    assert response.headers["page"] == "2"
    assert response.headers["per-page"] == "3"
    assert response.headers["total"] == "9"
    assert response.headers["total-pages"] == "3"


@pytest.mark.asyncio
async def test_get_one_data_connector(sanic_client: SanicASGITestClient, create_data_connector, user_headers) -> None:
    data_connector = await create_data_connector("A new data connector")
    data_connector_id = data_connector["id"]

    _, response = await sanic_client.get(f"/api/data/data_connectors/{data_connector_id}", headers=user_headers)

    assert response.status_code == 200, response.text
    assert response.json is not None
    data_connector = response.json
    assert data_connector.get("id") == data_connector_id
    assert data_connector.get("name") == "A new data connector"
    assert data_connector.get("namespace") == "user.doe"
    assert data_connector.get("slug") == "a-new-data-connector"


@pytest.mark.asyncio
async def test_get_one_by_slug_data_connector(
    sanic_client: SanicASGITestClient, create_data_connector, user_headers
) -> None:
    data_connector = await create_data_connector("A new data connector")
    namespace = data_connector["namespace"]
    slug = data_connector["slug"]

    _, response = await sanic_client.get(
        f"/api/data/namespaces/{namespace}/data_connectors/{slug}", headers=user_headers
    )

    assert response.status_code == 200, response.text
    assert response.json is not None
    data_connector = response.json
    assert data_connector.get("id") == data_connector["id"]
    assert data_connector.get("name") == "A new data connector"
    assert data_connector.get("namespace") == "user.doe"
    assert data_connector.get("slug") == "a-new-data-connector"


@pytest.mark.asyncio
async def test_patch_data_connector(sanic_client: SanicASGITestClient, create_data_connector, user_headers) -> None:
    data_connector = await create_data_connector("My data connector")

    headers = merge_headers(user_headers, {"If-Match": data_connector["etag"]})
    patch = {
        "name": "New Name",
        "description": "Updated data connector",
        "keywords": ["keyword 1", "keyword 2"],
        "visibility": "public",
        "storage": {
            "configuration": {"type": "azureblob"},
            "source_path": "new/src",
            "target_path": "new/target",
            "readonly": False,
        },
    }
    data_connector_id = data_connector["id"]
    _, response = await sanic_client.patch(
        f"/api/data/data_connectors/{data_connector_id}", headers=headers, json=patch
    )

    assert response.status_code == 200, response.text
    assert response.json is not None
    data_connector = response.json
    assert data_connector.get("name") == "New Name"
    assert data_connector.get("namespace") == "user.doe"
    assert data_connector.get("slug") == "my-data-connector"
    assert data_connector.get("storage") is not None
    storage = data_connector["storage"]
    assert storage.get("storage_type") == "azureblob"
    assert storage.get("source_path") == "new/src"
    assert storage.get("target_path") == "new/target"
    assert storage.get("readonly") is False
    assert data_connector.get("created_by") == "user"
    assert data_connector.get("visibility") == "public"
    assert data_connector.get("description") == "Updated data connector"
    assert set(data_connector.get("keywords")) == {"keyword 1", "keyword 2"}


@pytest.mark.asyncio
async def test_delete_data_connector(sanic_client: SanicASGITestClient, create_data_connector, user_headers) -> None:
    await create_data_connector("Data connector 1")
    data_connector = await create_data_connector("Data connector 2")
    await create_data_connector("Data connector 3")

    data_connector_id = data_connector["id"]
    _, response = await sanic_client.delete(f"/api/data/data_connectors/{data_connector_id}", headers=user_headers)

    assert response.status_code == 204, response.text

    _, response = await sanic_client.get("/api/data/data_connectors", headers=user_headers)

    assert response.status_code == 200, response.text
    assert {dc["name"] for dc in response.json} == {"Data connector 1", "Data connector 3"}
