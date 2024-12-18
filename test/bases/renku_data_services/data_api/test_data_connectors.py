import pytest
from sanic_testing.testing import SanicASGITestClient

from renku_data_services.users.models import UserInfo
from test.bases.renku_data_services.data_api.utils import merge_headers


@pytest.mark.asyncio
async def test_post_data_connector(sanic_client: SanicASGITestClient, regular_user: UserInfo, user_headers) -> None:
    payload = {
        "name": "My data connector",
        "slug": "my-data-connector",
        "description": "A data connector",
        "visibility": "public",
        "namespace": regular_user.namespace.slug,
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

    # Check that we can retrieve the data connector
    _, response = await sanic_client.get(f"/api/data/data_connectors/{data_connector["id"]}", headers=user_headers)
    assert response.status_code == 200, response.text
    assert response.json is not None
    assert response.json.get("id") == data_connector["id"]

    # Check that we can retrieve the data connector by slug
    _, response = await sanic_client.get(
        f"/api/data/namespaces/{data_connector["namespace"]
                                }/data_connectors/{data_connector["slug"]}",
        headers=user_headers,
    )
    assert response.status_code == 200, response.text
    assert response.json is not None
    assert response.json.get("id") == data_connector["id"]


@pytest.mark.asyncio
async def test_post_data_connector_with_s3_url(
    sanic_client: SanicASGITestClient, regular_user: UserInfo, user_headers
) -> None:
    payload = {
        "name": "My data connector",
        "slug": "my-data-connector",
        "description": "A data connector",
        "visibility": "public",
        "namespace": regular_user.namespace.slug,
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
    sanic_client: SanicASGITestClient, regular_user: UserInfo, user_headers
) -> None:
    payload = {
        "name": "My data connector",
        "slug": "my-data-connector",
        "description": "A data connector",
        "visibility": "public",
        "namespace": regular_user.namespace.slug,
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
async def test_post_data_connector_with_invalid_visibility(sanic_client: SanicASGITestClient, user_headers) -> None:
    payload = {"visibility": "random"}

    _, response = await sanic_client.post("/api/data/data_connectors", headers=user_headers, json=payload)

    assert response.status_code == 422, response.text
    assert "visibility: Input should be 'private' or 'public'" in response.json["error"]["message"]


@pytest.mark.asyncio
@pytest.mark.parametrize("keyword", ["invalid chars '", "Nön English"])
async def test_post_data_connector_with_invalid_keywords(
    sanic_client: SanicASGITestClient, user_headers, keyword
) -> None:
    payload = {"keywords": [keyword]}

    _, response = await sanic_client.post("/api/data/data_connectors", headers=user_headers, json=payload)

    assert response.status_code == 422, response.text
    assert "String should match pattern '^[A-Za-z0-9\\s\\-_.]*$'" in response.json["error"]["message"]


@pytest.mark.asyncio
async def test_post_data_connector_with_invalid_namespace(
    sanic_client: SanicASGITestClient,
    user_headers,
    member_1_user: UserInfo,
) -> None:
    namespace = member_1_user.namespace.slug
    _, response = await sanic_client.get(f"/api/data/namespaces/{namespace}", headers=user_headers)
    assert response.status_code == 200, response.text

    payload = {
        "name": "My data connector",
        "namespace": namespace,
        "storage": {
            "configuration": {
                "type": "s3",
                "provider": "AWS",
                "region": "us-east-1",
            },
            "source_path": "bucket/my-folder",
            "target_path": "my/target",
        },
    }
    _, response = await sanic_client.post("/api/data/data_connectors", headers=user_headers, json=payload)

    assert response.status_code == 403, response.text
    assert "you do not have sufficient permissions" in response.json["error"]["message"]


@pytest.mark.asyncio
async def test_post_data_connector_with_conflicting_slug(
    sanic_client: SanicASGITestClient, create_data_connector, user_headers
) -> None:
    data_connector_1 = await create_data_connector("Data connector 1")

    payload = {
        "name": "My data connector",
        "namespace": data_connector_1["namespace"],
        "slug": data_connector_1["slug"],
        "storage": {
            "configuration": {
                "type": "s3",
                "provider": "AWS",
            },
            "source_path": "bucket/my-folder",
            "target_path": "my/target",
        },
    }
    _, response = await sanic_client.post("/api/data/data_connectors", headers=user_headers, json=payload)

    assert response.status_code == 409, response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("headers_and_error", [("unauthorized_headers", 401), ("member_1_headers", 403)])
async def test_post_data_connector_without_namespace_permission(
    # NOTE: dynamically requesting async fixtures with an already running event loop causes errors in pytest.
    # to prevent this, all used fixtures have to also be listed again, so they exist at test execution time and
    # are loaded from cache
    sanic_client: SanicASGITestClient,
    user_headers,
    headers_and_error,
    unauthorized_headers,
    member_1_headers,
    request,
) -> None:
    headers_name, status_code = headers_and_error

    _, response = await sanic_client.post(
        "/api/data/groups", headers=user_headers, json={"name": "My Group", "slug": "my-group"}
    )
    assert response.status_code == 201, response.text

    headers = request.getfixturevalue(headers_name)
    payload = {
        "name": "My data connector",
        "namespace": "my-group",
        "storage": {
            "configuration": {
                "type": "s3",
                "provider": "AWS",
            },
            "source_path": "bucket/my-folder",
            "target_path": "my/target",
        },
    }
    _, response = await sanic_client.post("/api/data/data_connectors", headers=headers, json=payload)

    assert response.status_code == status_code, response.text


@pytest.mark.asyncio
async def test_post_data_connector_with_namespace_permission(
    sanic_client: SanicASGITestClient, user_headers, member_1_headers, member_1_user
) -> None:
    _, response = await sanic_client.post(
        "/api/data/groups", headers=user_headers, json={"name": "My Group", "slug": "my-group"}
    )
    assert response.status_code == 201, response.text
    patch = [{"id": member_1_user.id, "role": "editor"}]
    _, response = await sanic_client.patch("/api/data/groups/my-group/members", headers=user_headers, json=patch)
    assert response.status_code == 200

    payload = {
        "name": "My data connector",
        "namespace": "my-group",
        "storage": {
            "configuration": {
                "type": "s3",
                "provider": "AWS",
            },
            "source_path": "bucket/my-folder",
            "target_path": "my/target",
        },
    }
    _, response = await sanic_client.post("/api/data/data_connectors", headers=member_1_headers, json=payload)

    assert response.status_code == 201, response.text


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
@pytest.mark.parametrize("headers_name", ["unauthorized_headers", "member_1_headers"])
async def test_get_one_data_connector_unauthorized(
    # NOTE: dynamically requesting async fixtures with an already running event loop causes errors in pytest.
    # to prevent this, all used fixtures have to also be listed again, so they exist at test execution time and
    # are loaded from cache
    sanic_client: SanicASGITestClient,
    create_data_connector,
    headers_name,
    unauthorized_headers,
    member_1_headers,
    request,
) -> None:
    data_connector = await create_data_connector("A new data connector")
    data_connector_id = data_connector["id"]

    headers = request.getfixturevalue(headers_name)
    _, response = await sanic_client.get(f"/api/data/data_connectors/{data_connector_id}", headers=headers)

    assert response.status_code == 404, response.text


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
async def test_patch_data_connector_can_unset_storage_field(
    sanic_client: SanicASGITestClient, create_data_connector, user_headers
) -> None:
    initial_storage = {
        "configuration": {
            "provider": "AWS",
            "type": "s3",
            "region": "us-east-1",
            "access_key_id": "ACCESS KEY",
            "secret_access_key": "SECRET",
        },
        "source_path": "my-bucket",
        "target_path": "my_data",
    }
    data_connector = await create_data_connector("My data connector", storage=initial_storage)

    headers = merge_headers(user_headers, {"If-Match": data_connector["etag"]})
    data_connector_id = data_connector["id"]
    patch = {"storage": {"configuration": {"region": None, "access_key_id": None, "secret_access_key": None}}}
    _, response = await sanic_client.patch(
        f"/api/data/data_connectors/{data_connector_id}", headers=headers, json=patch
    )

    assert response.status_code == 200, response.text
    assert response.json is not None
    new_configuration = response.json["storage"]["configuration"]
    assert new_configuration is not None
    assert new_configuration["provider"] == "AWS"
    assert new_configuration["type"] == "s3"
    assert "region" not in new_configuration
    assert "access_key_id" not in new_configuration
    assert "secret_access_key" not in new_configuration
    assert len(response.json["storage"]["sensitive_fields"]) == 0


@pytest.mark.asyncio
async def test_patch_data_connector_visibility_to_private_hides_data_connector(
    sanic_client: SanicASGITestClient, create_data_connector, user_headers
) -> None:
    data_connector = await create_data_connector("My data connector", visibility="public")

    _, response = await sanic_client.get("/api/data/data_connectors")
    assert response.status_code == 200, response.text
    assert response.json is not None
    assert response.json[0]["name"] == "My data connector"

    headers = merge_headers(user_headers, {"If-Match": data_connector["etag"]})
    patch = {
        "visibility": "private",
    }
    data_connector_id = data_connector["id"]
    _, response = await sanic_client.patch(
        f"/api/data/data_connectors/{data_connector_id}", headers=headers, json=patch
    )
    assert response.status_code == 200, response.text

    _, response = await sanic_client.get("/api/data/data_connectors")

    assert len(response.json) == 0


@pytest.mark.asyncio
async def test_patch_data_connector_visibility_to_public_shows_data_connector(
    sanic_client: SanicASGITestClient, create_data_connector, user_headers
) -> None:
    data_connector = await create_data_connector("My data connector", visibility="private")

    _, response = await sanic_client.get("/api/data/data_connectors")
    assert response.status_code == 200, response.text
    assert response.json is not None
    assert len(response.json) == 0

    headers = merge_headers(user_headers, {"If-Match": data_connector["etag"]})
    patch = {
        "visibility": "public",
    }
    data_connector_id = data_connector["id"]
    _, response = await sanic_client.patch(
        f"/api/data/data_connectors/{data_connector_id}", headers=headers, json=patch
    )
    assert response.status_code == 200, response.text

    _, response = await sanic_client.get("/api/data/data_connectors")

    assert response.status_code == 200, response.text
    assert response.json is not None
    assert response.json[0]["name"] == "My data connector"


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["id", "created_by", "creation_date"])
async def test_patch_data_connector_reserved_fields_are_forbidden(
    sanic_client: SanicASGITestClient, create_data_connector, user_headers, field
) -> None:
    data_connector = await create_data_connector("My data connector")
    original_value = data_connector[field]

    headers = merge_headers(user_headers, {"If-Match": data_connector["etag"]})
    patch = {
        field: "new-value",
    }
    data_connector_id = data_connector["id"]
    _, response = await sanic_client.patch(
        f"/api/data/data_connectors/{data_connector_id}", headers=headers, json=patch
    )

    assert response.status_code == 422, response.text
    assert f"{field}: Extra inputs are not permitted" in response.text

    # Check that the field's value didn't change
    _, response = await sanic_client.get(f"/api/data/data_connectors/{data_connector_id}", headers=user_headers)
    assert response.status_code == 200, response.text
    data_connector = response.json
    assert data_connector[field] == original_value


@pytest.mark.asyncio
async def test_patch_data_connector_without_if_match_header(
    sanic_client: SanicASGITestClient, create_data_connector, user_headers
) -> None:
    data_connector = await create_data_connector("My data connector")
    original_value = data_connector["name"]

    patch = {
        "name": "New Name",
    }
    data_connector_id = data_connector["id"]
    _, response = await sanic_client.patch(
        f"/api/data/data_connectors/{data_connector_id}", headers=user_headers, json=patch
    )

    assert response.status_code == 428, response.text
    assert "If-Match header not provided" in response.text

    # Check that the field's value didn't change
    _, response = await sanic_client.get(f"/api/data/data_connectors/{data_connector_id}", headers=user_headers)
    assert response.status_code == 200, response.text
    data_connector = response.json
    assert data_connector["name"] == original_value


@pytest.mark.asyncio
async def test_patch_data_connector_namespace(
    sanic_client: SanicASGITestClient, create_data_connector, user_headers
) -> None:
    _, response = await sanic_client.post(
        "/api/data/groups", headers=user_headers, json={"name": "My Group", "slug": "my-group"}
    )
    assert response.status_code == 201, response.text
    data_connector = await create_data_connector("My data connector")

    headers = merge_headers(user_headers, {"If-Match": data_connector["etag"]})
    patch = {"namespace": "my-group"}
    data_connector_id = data_connector["id"]
    _, response = await sanic_client.patch(
        f"/api/data/data_connectors/{data_connector_id}", headers=headers, json=patch
    )

    assert response.status_code == 200, response.text
    assert response.json is not None
    data_connector = response.json
    assert data_connector.get("id") == data_connector_id
    assert data_connector.get("name") == "My data connector"
    assert data_connector.get("namespace") == "my-group"
    assert data_connector.get("slug") == "my-data-connector"

    # Check that we can retrieve the data connector by slug
    _, response = await sanic_client.get(
        f"/api/data/namespaces/{data_connector["namespace"]
                                }/data_connectors/{data_connector["slug"]}",
        headers=user_headers,
    )
    assert response.status_code == 200, response.text
    assert response.json is not None
    assert response.json.get("id") == data_connector["id"]


@pytest.mark.asyncio
async def test_patch_data_connector_with_invalid_namespace(
    sanic_client: SanicASGITestClient, create_data_connector, user_headers, member_1_user: UserInfo
) -> None:
    namespace = member_1_user.namespace.slug
    _, response = await sanic_client.get(f"/api/data/namespaces/{namespace}", headers=user_headers)
    assert response.status_code == 200, response.text
    data_connector = await create_data_connector("My data connector")

    headers = merge_headers(user_headers, {"If-Match": data_connector["etag"]})
    patch = {
        "namespace": namespace,
    }
    data_connector_id = data_connector["id"]
    _, response = await sanic_client.patch(
        f"/api/data/data_connectors/{data_connector_id}", headers=headers, json=patch
    )

    assert response.status_code == 403, response.text
    assert "you do not have sufficient permissions" in response.json["error"]["message"]


@pytest.mark.asyncio
async def test_patch_data_connector_as_editor(
    sanic_client: SanicASGITestClient,
    create_data_connector,
    admin_headers,
    admin_user,
    user_headers,
    regular_user,
) -> None:
    _, response = await sanic_client.post(
        "/api/data/groups", headers=admin_headers, json={"name": "My Group", "slug": "my-group"}
    )
    assert response.status_code == 201, response.text
    patch = [{"id": regular_user.id, "role": "editor"}]
    _, response = await sanic_client.patch("/api/data/groups/my-group/members", headers=admin_headers, json=patch)
    assert response.status_code == 200, response.text
    data_connector = await create_data_connector(
        "My data connector", user=admin_user, headers=admin_headers, namespace="my-group"
    )
    data_connector_id = data_connector["id"]

    headers = merge_headers(user_headers, {"If-Match": data_connector["etag"]})
    patch = {
        # Test that we do not require DELETE permission when sending the current namepace
        "namespace": data_connector["namespace"],
        # Test that we do not require DELETE permission when sending the current visibility
        "visibility": data_connector["visibility"],
        "description": "A new description",
    }
    _, response = await sanic_client.patch(
        f"/api/data/data_connectors/{data_connector_id}", headers=headers, json=patch
    )

    assert response.status_code == 200, response.text
    assert response.json is not None
    assert response.json.get("namespace") == data_connector["namespace"]
    assert response.json.get("visibility") == data_connector["visibility"]
    assert response.json.get("description") == "A new description"


@pytest.mark.asyncio
async def test_patch_data_connector_slug(
    sanic_client: SanicASGITestClient,
    create_data_connector,
    user_headers,
) -> None:
    await create_data_connector("Data connector 1")
    await create_data_connector("Data connector 2")
    data_connector = await create_data_connector("My data connector")
    data_connector_id = data_connector["id"]
    namespace = data_connector["namespace"]
    old_slug = data_connector["slug"]
    await create_data_connector("Data connector 3")

    # Patch a data connector
    headers = merge_headers(user_headers, {"If-Match": data_connector["etag"]})
    new_slug = "some-updated-slug"
    patch = {"slug": new_slug}
    _, response = await sanic_client.patch(
        f"/api/data/data_connectors/{data_connector_id}", headers=headers, json=patch
    )

    assert response.status_code == 200, response.text

    # Check that the data connector's slug has been updated
    _, response = await sanic_client.get(f"/api/data/data_connectors/{data_connector_id}", headers=user_headers)
    assert response.status_code == 200, response.text
    data_connector = response.json
    assert data_connector["id"] == data_connector_id
    assert data_connector["name"] == "My data connector"
    assert data_connector["namespace"] == namespace
    assert data_connector["slug"] == new_slug

    # Check that we can get the data connector with the new slug
    _, response = await sanic_client.get(
        f"/api/data/namespaces/{namespace}/data_connectors/{new_slug}", headers=user_headers
    )
    assert response.status_code == 200, response.text
    assert response.json is not None
    assert response.json.get("id") == data_connector_id
    assert data_connector["namespace"] == namespace
    assert data_connector["slug"] == new_slug

    # Check that we can get the data connector with the old slug
    _, response = await sanic_client.get(
        f"/api/data/namespaces/{namespace}/data_connectors/{old_slug}", headers=user_headers
    )
    assert response.status_code == 200, response.text
    assert response.json is not None
    assert response.json.get("id") == data_connector_id
    assert data_connector["namespace"] == namespace
    assert data_connector["slug"] == new_slug


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


@pytest.mark.asyncio
async def test_get_data_connector_project_links_empty(
    sanic_client: SanicASGITestClient, create_data_connector, user_headers
) -> None:
    data_connector = await create_data_connector("Data connector 1")

    data_connector_id = data_connector["id"]
    _, response = await sanic_client.get(
        f"/api/data/data_connectors/{data_connector_id}/project_links", headers=user_headers
    )

    assert response.status_code == 200, response.text
    assert response.json is not None
    assert len(response.json) == 0


@pytest.mark.asyncio
async def test_post_data_connector_project_link(
    sanic_client: SanicASGITestClient, create_data_connector, create_project, user_headers
) -> None:
    data_connector = await create_data_connector("Data connector 1")
    project = await create_project("Project A")

    data_connector_id = data_connector["id"]
    project_id = project["id"]
    payload = {"project_id": project_id}
    _, response = await sanic_client.post(
        f"/api/data/data_connectors/{data_connector_id}/project_links", headers=user_headers, json=payload
    )

    assert response.status_code == 201, response.text
    assert response.json is not None
    link = response.json
    assert link.get("data_connector_id") == data_connector_id
    assert link.get("project_id") == project_id
    assert link.get("created_by") == "user"

    # Check that the links list from the data connector is not empty now
    _, response = await sanic_client.get(
        f"/api/data/data_connectors/{data_connector_id}/project_links", headers=user_headers
    )

    assert response.status_code == 200, response.text
    assert response.json is not None
    assert len(response.json) == 1
    assert response.json[0].get("id") == link["id"]
    assert response.json[0].get("data_connector_id") == data_connector_id
    assert response.json[0].get("project_id") == project_id

    # Check that the links list to the project is not empty now
    _, response = await sanic_client.get(f"/api/data/projects/{project_id}/data_connector_links", headers=user_headers)

    assert response.status_code == 200, response.text
    assert response.json is not None
    assert len(response.json) == 1
    assert response.json[0].get("id") == link["id"]
    assert response.json[0].get("data_connector_id") == data_connector_id
    assert response.json[0].get("project_id") == project_id


@pytest.mark.asyncio
async def test_post_data_connector_project_link_already_exists(
    sanic_client: SanicASGITestClient, create_data_connector, create_project, user_headers
) -> None:
    data_connector = await create_data_connector("Data connector 1")
    project = await create_project("Project A")
    data_connector_id = data_connector["id"]
    project_id = project["id"]
    payload = {"project_id": project_id}
    _, response = await sanic_client.post(
        f"/api/data/data_connectors/{data_connector_id}/project_links", headers=user_headers, json=payload
    )
    assert response.status_code == 201, response.text

    _, response = await sanic_client.post(
        f"/api/data/data_connectors/{data_connector_id}/project_links", headers=user_headers, json=payload
    )
    assert response.status_code == 409, response.text


@pytest.mark.asyncio
async def test_post_data_connector_project_link_unauthorized_if_not_project_editor(
    sanic_client: SanicASGITestClient,
    create_data_connector,
    create_project,
    user_headers,
    member_1_headers,
    member_1_user,
) -> None:
    _, response = await sanic_client.post(
        "/api/data/groups", headers=user_headers, json={"name": "My Group", "slug": "my-group"}
    )
    assert response.status_code == 201, response.text
    patch = [{"id": member_1_user.id, "role": "owner"}]
    _, response = await sanic_client.patch("/api/data/groups/my-group/members", headers=user_headers, json=patch)
    assert response.status_code == 200
    data_connector = await create_data_connector("Data connector 1", namespace="my-group")
    data_connector_id = data_connector["id"]
    project = await create_project("Project A")
    project_id = project["id"]
    patch = [{"id": member_1_user.id, "role": "viewer"}]
    _, response = await sanic_client.patch(f"/api/data/projects/{project_id}/members", headers=user_headers, json=patch)
    assert response.status_code == 200, response.text

    # Check that "member_1" can view the project and data connector
    _, response = await sanic_client.get(f"/api/data/data_connectors/{data_connector_id}", headers=member_1_headers)
    assert response.status_code == 200, response.text
    _, response = await sanic_client.get(f"/api/data/projects/{project_id}", headers=member_1_headers)
    assert response.status_code == 200, response.text

    payload = {"project_id": project_id}
    _, response = await sanic_client.post(
        f"/api/data/data_connectors/{data_connector_id}/project_links", headers=member_1_headers, json=payload
    )

    assert response.status_code == 404, response.text


@pytest.mark.asyncio
async def test_post_data_connector_project_link_unauthorized_if_not_data_connector_editor(
    sanic_client: SanicASGITestClient,
    create_data_connector,
    create_project,
    user_headers,
    member_1_headers,
    member_1_user,
) -> None:
    _, response = await sanic_client.post(
        "/api/data/groups", headers=user_headers, json={"name": "My Group", "slug": "my-group"}
    )
    assert response.status_code == 201, response.text
    patch = [{"id": member_1_user.id, "role": "viewer"}]
    _, response = await sanic_client.patch("/api/data/groups/my-group/members", headers=user_headers, json=patch)
    assert response.status_code == 200
    data_connector = await create_data_connector("Data connector 1", namespace="my-group")
    data_connector_id = data_connector["id"]
    project = await create_project("Project A")
    project_id = project["id"]
    patch = [{"id": member_1_user.id, "role": "owner"}]
    _, response = await sanic_client.patch(f"/api/data/projects/{project_id}/members", headers=user_headers, json=patch)
    assert response.status_code == 200, response.text

    # Check that "member_1" can view the project and data connector
    _, response = await sanic_client.get(f"/api/data/data_connectors/{data_connector_id}", headers=member_1_headers)
    assert response.status_code == 200, response.text
    _, response = await sanic_client.get(f"/api/data/projects/{project_id}", headers=member_1_headers)
    assert response.status_code == 200, response.text

    payload = {"project_id": project_id}
    _, response = await sanic_client.post(
        f"/api/data/data_connectors/{data_connector_id}/project_links", headers=member_1_headers, json=payload
    )

    assert response.status_code == 404, response.text


@pytest.mark.asyncio
async def test_post_data_connector_project_link_public_data_connector(
    sanic_client: SanicASGITestClient,
    create_data_connector,
    create_project,
    user_headers,
    member_1_headers,
    member_1_user,
) -> None:
    data_connector = await create_data_connector(
        "Data connector 1", user=member_1_user, headers=member_1_headers, visibility="public"
    )
    data_connector_id = data_connector["id"]
    project = await create_project("Project A")
    project_id = project["id"]

    # Check that "regular_user" can view the project and data connector
    _, response = await sanic_client.get(f"/api/data/data_connectors/{data_connector_id}", headers=user_headers)
    assert response.status_code == 200, response.text
    _, response = await sanic_client.get(f"/api/data/projects/{project_id}", headers=user_headers)
    assert response.status_code == 200, response.text

    payload = {"project_id": project_id}
    _, response = await sanic_client.post(
        f"/api/data/data_connectors/{data_connector_id}/project_links", headers=user_headers, json=payload
    )

    assert response.status_code == 201, response.text
    assert response.json is not None
    link = response.json
    assert link.get("data_connector_id") == data_connector_id
    assert link.get("project_id") == project_id
    assert link.get("created_by") == "user"


@pytest.mark.asyncio
@pytest.mark.parametrize("project_role", ["viewer", "editor", "owner"])
async def test_post_data_connector_project_link_extends_read_access(
    sanic_client: SanicASGITestClient,
    create_data_connector,
    create_project,
    user_headers,
    member_1_headers,
    member_1_user,
    project_role,
) -> None:
    data_connector = await create_data_connector("Data connector 1")
    data_connector_id = data_connector["id"]
    project = await create_project("Project A")
    project_id = project["id"]
    patch = [{"id": member_1_user.id, "role": project_role}]
    _, response = await sanic_client.patch(f"/api/data/projects/{project_id}/members", headers=user_headers, json=patch)
    assert response.status_code == 200, response.text

    # Check that "member_1" can view the project
    _, response = await sanic_client.get(f"/api/data/projects/{project_id}", headers=member_1_headers)
    assert response.status_code == 200, response.text
    # Check that "member_1" cannot view the data connector
    _, response = await sanic_client.get(f"/api/data/data_connectors/{data_connector_id}", headers=member_1_headers)
    assert response.status_code == 404, response.text

    data_connector_id = data_connector["id"]
    project_id = project["id"]
    payload = {"project_id": project_id}
    _, response = await sanic_client.post(
        f"/api/data/data_connectors/{data_connector_id}/project_links", headers=user_headers, json=payload
    )
    assert response.status_code == 201, response.text

    # Check that "member_1" can now view the data connector
    _, response = await sanic_client.get(f"/api/data/data_connectors/{data_connector_id}", headers=member_1_headers)
    assert response.status_code == 200, response.text
    assert response.json is not None
    assert response.json.get("id") == data_connector_id
    assert response.json.get("name") == "Data connector 1"
    assert response.json.get("namespace") == "user.doe"
    assert response.json.get("slug") == "data-connector-1"


@pytest.mark.asyncio
@pytest.mark.parametrize("group_role", ["viewer", "editor", "owner"])
async def test_post_data_connector_project_link_does_not_extend_access_to_parent_group_members(
    sanic_client: SanicASGITestClient,
    create_data_connector,
    user_headers,
    member_1_headers,
    member_1_user,
    group_role,
) -> None:
    data_connector = await create_data_connector("Data connector 1")
    data_connector_id = data_connector["id"]
    _, response = await sanic_client.post(
        "/api/data/groups", headers=user_headers, json={"name": "My Group", "slug": "my-group"}
    )
    assert response.status_code == 201, response.text
    patch = [{"id": member_1_user.id, "role": group_role}]
    _, response = await sanic_client.patch("/api/data/groups/my-group/members", headers=user_headers, json=patch)
    assert response.status_code == 200
    payload = {"name": "Project A", "namespace": "my-group"}
    _, response = await sanic_client.post("/api/data/projects", headers=user_headers, json=payload)
    assert response.status_code == 201
    project = response.json
    project_id = project["id"]

    # Check that "member_1" can view the project
    _, response = await sanic_client.get(f"/api/data/projects/{project_id}", headers=member_1_headers)
    assert response.status_code == 200, response.text
    # Check that "member_1" cannot view the data connector
    _, response = await sanic_client.get(f"/api/data/data_connectors/{data_connector_id}", headers=member_1_headers)
    assert response.status_code == 404, response.text

    data_connector_id = data_connector["id"]
    project_id = project["id"]
    payload = {"project_id": project_id}
    _, response = await sanic_client.post(
        f"/api/data/data_connectors/{data_connector_id}/project_links", headers=user_headers, json=payload
    )
    assert response.status_code == 201, response.text

    # Check that "member_1" can still not view the data connector
    _, response = await sanic_client.get(f"/api/data/data_connectors/{data_connector_id}", headers=member_1_headers)
    assert response.status_code == 404, response.text


@pytest.mark.asyncio
async def test_delete_data_connector_project_link(
    sanic_client: SanicASGITestClient, create_data_connector, create_project, user_headers
) -> None:
    data_connector = await create_data_connector("Data connector 1")
    project = await create_project("Project A")
    data_connector_id = data_connector["id"]
    project_id = project["id"]
    payload = {"project_id": project_id}
    _, response = await sanic_client.post(
        f"/api/data/data_connectors/{data_connector_id}/project_links", headers=user_headers, json=payload
    )
    assert response.status_code == 201, response.text
    link = response.json

    _, response = await sanic_client.delete(
        f"/api/data/data_connectors/{data_connector_id}/project_links/{link["id"]}", headers=user_headers
    )

    assert response.status_code == 204, response.text

    # Check that the links list from the data connector is empty now
    _, response = await sanic_client.get(
        f"/api/data/data_connectors/{data_connector_id}/project_links", headers=user_headers
    )

    assert response.status_code == 200, response.text
    assert response.json is not None
    assert len(response.json) == 0

    # Check that the links list to the project is empty now
    _, response = await sanic_client.get(f"/api/data/projects/{project_id}/data_connector_links", headers=user_headers)

    assert response.status_code == 200, response.text
    assert response.json is not None
    assert len(response.json) == 0

    # Check that calling delete again returns a 204
    _, response = await sanic_client.delete(
        f"/api/data/data_connectors/{data_connector_id}/project_links/{link["id"]}", headers=user_headers
    )

    assert response.status_code == 204, response.text


@pytest.mark.asyncio
async def test_delete_data_connector_after_linking(
    sanic_client: SanicASGITestClient, create_data_connector, create_project, user_headers
) -> None:
    data_connector = await create_data_connector("Data connector 1")
    project = await create_project("Project A")
    data_connector_id = data_connector["id"]
    project_id = project["id"]
    payload = {"project_id": project_id}
    _, response = await sanic_client.post(
        f"/api/data/data_connectors/{data_connector_id}/project_links", headers=user_headers, json=payload
    )
    assert response.status_code == 201, response.text

    _, response = await sanic_client.delete(f"/api/data/data_connectors/{data_connector_id}", headers=user_headers)

    assert response.status_code == 204, response.text

    # Check that the project still exists
    _, response = await sanic_client.get(f"/api/data/projects/{project_id}", headers=user_headers)
    assert response.status_code == 200, response.text

    # Check that the links list to the project is empty now
    _, response = await sanic_client.get(f"/api/data/projects/{project_id}/data_connector_links", headers=user_headers)

    assert response.status_code == 200, response.text
    assert response.json is not None
    assert len(response.json) == 0


@pytest.mark.asyncio
async def test_delete_project_after_linking(
    sanic_client: SanicASGITestClient, create_data_connector, create_project, user_headers
) -> None:
    data_connector = await create_data_connector("Data connector 1")
    project = await create_project("Project A")
    data_connector_id = data_connector["id"]
    project_id = project["id"]
    payload = {"project_id": project_id}
    _, response = await sanic_client.post(
        f"/api/data/data_connectors/{data_connector_id}/project_links", headers=user_headers, json=payload
    )
    assert response.status_code == 201, response.text

    _, response = await sanic_client.delete(f"/api/data/projects/{project_id}", headers=user_headers)

    assert response.status_code == 204, response.text

    # Check that the data connector still exists
    _, response = await sanic_client.get(f"/api/data/data_connectors/{data_connector_id}", headers=user_headers)

    assert response.status_code == 200, response.text

    # Check that the links list from the data connector is empty now
    _, response = await sanic_client.get(
        f"/api/data/data_connectors/{data_connector_id}/project_links", headers=user_headers
    )

    assert response.status_code == 200, response.text
    assert response.json is not None
    assert len(response.json) == 0


@pytest.mark.asyncio
async def test_patch_data_connector_secrets(
    sanic_client: SanicASGITestClient, create_data_connector, user_headers
) -> None:
    data_connector = await create_data_connector("My data connector")
    data_connector_id = data_connector["id"]

    payload = [
        {"name": "access_key_id", "value": "access key id value"},
        {"name": "secret_access_key", "value": "secret access key value"},
    ]
    _, response = await sanic_client.patch(
        f"/api/data/data_connectors/{data_connector_id}/secrets", headers=user_headers, json=payload
    )

    assert response.status_code == 200, response.json
    assert response.json is not None
    secrets = response.json
    assert len(secrets) == 2
    assert {s["name"] for s in secrets} == {"access_key_id", "secret_access_key"}

    # Check that the secrets are returned from a GET request
    _, response = await sanic_client.get(f"/api/data/data_connectors/{data_connector_id}/secrets", headers=user_headers)
    assert response.status_code == 200, response.json
    assert response.json is not None
    secrets = response.json
    assert len(secrets) == 2
    assert {s["name"] for s in secrets} == {"access_key_id", "secret_access_key"}

    # Check that the data connector is referenced from the first user secret
    user_secret_id = secrets[0]["secret_id"]
    _, response = await sanic_client.get(f"/api/data/user/secrets/{user_secret_id}", headers=user_headers)
    assert response.status_code == 200, response.json
    assert response.json is not None
    assert response.json.get("data_connector_ids") is not None
    assert {id for id in response.json.get("data_connector_ids")} == {data_connector_id}


@pytest.mark.asyncio
async def test_patch_data_connector_secrets_update_secrets(
    sanic_client: SanicASGITestClient, create_data_connector, user_headers
) -> None:
    data_connector = await create_data_connector("My data connector")
    data_connector_id = data_connector["id"]
    payload = [
        {"name": "access_key_id", "value": "access key id value"},
        {"name": "secret_access_key", "value": "secret access key value"},
    ]
    _, response = await sanic_client.patch(
        f"/api/data/data_connectors/{data_connector_id}/secrets", headers=user_headers, json=payload
    )
    assert response.status_code == 200, response.json
    assert response.json is not None
    secrets = response.json
    assert len(secrets) == 2
    assert {s["name"] for s in secrets} == {"access_key_id", "secret_access_key"}
    secret_ids = {s["secret_id"] for s in secrets}

    payload = [
        {"name": "access_key_id", "value": "new access key id value"},
        {"name": "secret_access_key", "value": "new secret access key value"},
    ]
    _, response = await sanic_client.patch(
        f"/api/data/data_connectors/{data_connector_id}/secrets", headers=user_headers, json=payload
    )

    assert response.status_code == 200, response.json
    assert response.json is not None
    secrets = response.json
    assert len(secrets) == 2
    assert {s["name"] for s in secrets} == {"access_key_id", "secret_access_key"}
    assert {s["secret_id"] for s in secrets} == secret_ids

    # Check that the secrets are returned from a GET request
    _, response = await sanic_client.get(f"/api/data/data_connectors/{data_connector_id}/secrets", headers=user_headers)
    assert response.status_code == 200, response.json
    assert response.json is not None
    secrets = response.json
    assert len(secrets) == 2
    assert {s["name"] for s in secrets} == {"access_key_id", "secret_access_key"}
    assert {s["secret_id"] for s in secrets} == secret_ids


@pytest.mark.asyncio
async def test_patch_data_connector_secrets_add_and_remove_secrets(
    sanic_client: SanicASGITestClient, create_data_connector, user_headers
) -> None:
    data_connector = await create_data_connector("My data connector")
    data_connector_id = data_connector["id"]
    payload = [
        {"name": "access_key_id", "value": "access key id value"},
        {"name": "secret_access_key", "value": "secret access key value"},
    ]
    _, response = await sanic_client.patch(
        f"/api/data/data_connectors/{data_connector_id}/secrets", headers=user_headers, json=payload
    )
    assert response.status_code == 200, response.json
    assert response.json is not None
    secrets = response.json
    assert len(secrets) == 2
    assert {s["name"] for s in secrets} == {"access_key_id", "secret_access_key"}
    access_key_id_secret_id = next(filter(lambda s: s["name"] == "access_key_id", secrets), None)

    payload = [
        {"name": "access_key_id", "value": "new access key id value"},
        {"name": "secret_access_key", "value": None},
        {"name": "password", "value": "password"},
    ]
    _, response = await sanic_client.patch(
        f"/api/data/data_connectors/{data_connector_id}/secrets", headers=user_headers, json=payload
    )

    assert response.status_code == 200, response.json
    assert response.json is not None
    secrets = response.json
    assert len(secrets) == 2
    assert {s["name"] for s in secrets} == {"access_key_id", "password"}
    new_access_key_id_secret_id = next(filter(lambda s: s["name"] == "access_key_id", secrets), None)
    assert new_access_key_id_secret_id == access_key_id_secret_id

    # Check that the secrets are returned from a GET request
    _, response = await sanic_client.get(f"/api/data/data_connectors/{data_connector_id}/secrets", headers=user_headers)
    assert response.status_code == 200, response.json
    assert response.json is not None
    secrets = response.json
    assert len(secrets) == 2
    assert {s["name"] for s in secrets} == {"access_key_id", "password"}

    # Check the associated secrets
    _, response = await sanic_client.get("/api/data/user/secrets", params={"kind": "storage"}, headers=user_headers)

    assert response.status_code == 200
    assert response.json is not None
    assert len(response.json) == 2
    assert {s["name"] for s in secrets} == {"access_key_id", "password"}


@pytest.mark.asyncio
async def test_delete_data_connector_secrets(
    sanic_client: SanicASGITestClient, create_data_connector, user_headers
) -> None:
    data_connector = await create_data_connector("My data connector")
    data_connector_id = data_connector["id"]
    payload = [
        {"name": "access_key_id", "value": "access key id value"},
        {"name": "secret_access_key", "value": "secret access key value"},
    ]
    _, response = await sanic_client.patch(
        f"/api/data/data_connectors/{data_connector_id}/secrets", headers=user_headers, json=payload
    )
    assert response.status_code == 200, response.json
    assert response.json is not None
    secrets = response.json
    assert len(secrets) == 2
    assert {s["name"] for s in secrets} == {"access_key_id", "secret_access_key"}

    _, response = await sanic_client.delete(
        f"/api/data/data_connectors/{data_connector_id}/secrets", headers=user_headers
    )

    assert response.status_code == 204, response.json

    # Check that the secrets list is empty from the GET request
    _, response = await sanic_client.get(f"/api/data/data_connectors/{data_connector_id}/secrets", headers=user_headers)
    assert response.status_code == 200, response.json
    assert response.json == [], response.json

    # Check that the associated secrets are deleted
    _, response = await sanic_client.get("/api/data/user/secrets", params={"kind": "storage"}, headers=user_headers)

    assert response.status_code == 200
    assert response.json == [], response.json


@pytest.mark.asyncio
async def test_get_project_permissions_unauthorized(
    sanic_client, create_data_connector, admin_headers, admin_user, user_headers
) -> None:
    data_connector = await create_data_connector("My data connector", user=admin_user, headers=admin_headers)
    data_connector_id = data_connector["id"]

    _, response = await sanic_client.get(f"/api/data/projects/{data_connector_id}/permissions", headers=user_headers)

    assert response.status_code == 404, response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["viewer", "editor", "owner"])
async def test_get_data_connector_permissions_cascading_from_group(
    sanic_client: SanicASGITestClient,
    create_data_connector,
    admin_headers,
    admin_user,
    user_headers,
    regular_user,
    role,
) -> None:
    _, response = await sanic_client.post(
        "/api/data/groups", headers=admin_headers, json={"name": "My Group", "slug": "my-group"}
    )
    assert response.status_code == 201, response.text
    patch = [{"id": regular_user.id, "role": role}]
    _, response = await sanic_client.patch("/api/data/groups/my-group/members", headers=admin_headers, json=patch)
    assert response.status_code == 200, response.text
    data_connector = await create_data_connector(
        "My data connector", user=admin_user, headers=admin_headers, namespace="my-group"
    )
    data_connector_id = data_connector["id"]

    expected_permissions = dict(
        write=False,
        delete=False,
        change_membership=False,
    )
    if role == "editor" or role == "owner":
        expected_permissions["write"] = True
    if role == "owner":
        expected_permissions["delete"] = True
        expected_permissions["change_membership"] = True

    _, response = await sanic_client.get(
        f"/api/data/data_connectors/{data_connector_id}/permissions", headers=user_headers
    )

    assert response.status_code == 200, response.text
    assert response.json is not None
    permissions = response.json
    assert permissions.get("write") == expected_permissions["write"]
    assert permissions.get("delete") == expected_permissions["delete"]
    assert permissions.get("change_membership") == expected_permissions["change_membership"]
