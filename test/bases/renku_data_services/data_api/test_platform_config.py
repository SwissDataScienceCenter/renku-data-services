"""Tests for platform config blueprints."""

import pytest
from sanic_testing.testing import SanicASGITestClient

from renku_data_services.data_api.dependencies import DependencyManager
from test.bases.renku_data_services.data_api.utils import merge_headers


@pytest.mark.asyncio
async def test_get_platform_config(app_manager: DependencyManager, sanic_client: SanicASGITestClient) -> None:
    _, res = await sanic_client.get("/api/data/platform/config")

    assert res.status_code == 200, res.text
    assert res.json is not None
    platform_config = res.json
    assert platform_config.get("incident_banner") == ""
    assert platform_config.get("etag") != ""


@pytest.mark.asyncio
async def test_patch_platform_config(sanic_client: SanicASGITestClient, admin_headers: dict[str, str]) -> None:
    _, res = await sanic_client.get("/api/data/platform/config")
    initial_config = res.json

    headers = merge_headers(admin_headers, {"If-Match": initial_config["etag"]})
    payload = {"incident_banner": "Some content"}

    _, res = await sanic_client.patch("/api/data/platform/config", headers=headers, json=payload)

    assert res.status_code == 200, res.text
    assert res.json is not None
    platform_config = res.json
    assert platform_config.get("incident_banner") == "Some content"
    assert platform_config.get("etag") != initial_config["etag"]


@pytest.mark.asyncio
async def test_patch_platform_config_unauthorized(
    sanic_client: SanicASGITestClient, user_headers: dict[str, str]
) -> None:
    _, res = await sanic_client.get("/api/data/platform/config")
    initial_config = res.json

    headers = merge_headers(user_headers, {"If-Match": initial_config["etag"]})
    payload = {"incident_banner": "Some content"}

    _, res = await sanic_client.patch("/api/data/platform/config", headers=headers, json=payload)

    assert res.status_code == 403, res.text


@pytest.mark.asyncio
async def test_get_redirects(app_manager: DependencyManager, sanic_client: SanicASGITestClient) -> None:
    parameters = {"page": 1, "per_page": 5}
    _, res = await sanic_client.get("/api/data/platform/redirects", params=parameters)

    assert res.status_code == 200, res.text
    assert res.json is not None
    assert res.headers["page"] == "1"
    assert res.headers["per-page"] == "5"
    assert res.headers["total"] == "0"
    assert res.headers["total-pages"] == "1"

    # redirects = res.json
    # assert redirects.get("etag") != ""


@pytest.mark.asyncio
async def test_post_platform_config(sanic_client: SanicASGITestClient, admin_headers: dict[str, str]) -> None:
    _, res = await sanic_client.get("/api/data/platform/redirects")
    initial_config = res.json

    headers = merge_headers(admin_headers, {"If-Match": initial_config["etag"]})
    payload = {"source_url": "/projects/ns/project-slug", "target_url": "/p/ns/project-slug"}

    _, res = await sanic_client.post("/api/data/platform/redirects", headers=headers, json=payload)
    assert res.status_code == 500, res.text

    # assert res.status_code == 201, res.text
    # assert res.json is not None
    # platform_config = res.json
    # assert platform_config.get("incident_banner") == "Some content"
    # assert platform_config.get("etag") != initial_config["etag"]


@pytest.mark.asyncio
async def test_post_platform_config_unauthorized(
    sanic_client: SanicASGITestClient, user_headers: dict[str, str]
) -> None:
    _, res = await sanic_client.get("/api/data/platform/redirects")
    initial_config = res.json

    headers = merge_headers(user_headers, {"If-Match": initial_config["etag"]})
    payload = {"source_url": "/projects/ns/project-slug", "target_url": "/p/ns/project-slug"}

    _, res = await sanic_client.post("/api/data/platform/redirects", headers=headers, json=payload)

    assert res.status_code == 403, res.text
