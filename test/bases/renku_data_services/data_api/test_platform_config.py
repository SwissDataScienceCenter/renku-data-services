"""Tests for platform config blueprints."""

from typing import Any

import pytest
from sanic_testing.testing import SanicASGITestClient

from renku_data_services.app_config import Config
from renku_data_services.base_models.core import InternalServiceAdmin, ServiceAdminId
from test.bases.renku_data_services.data_api.utils import merge_headers


@pytest.fixture
def initialize_platform_config(app_config: Config, sanic_client: SanicASGITestClient):
    async def initialize_platform_config_helper() -> dict[str, Any]:
        await app_config.platform_repo.create_initial_config(user=InternalServiceAdmin(id=ServiceAdminId.migrations))

        _, res = await sanic_client.get("/api/data/platform/config")

        assert res.status_code == 200, res.text
        assert res.json is not None
        platform_config = res.json
        assert platform_config.get("incident_banner") == ""
        assert platform_config.get("etag") != ""

        return platform_config

    return initialize_platform_config_helper


@pytest.mark.asyncio
async def test_platform_config_init(app_config: Config, sanic_client: SanicASGITestClient) -> None:
    await app_config.platform_repo.create_initial_config(user=InternalServiceAdmin(id=ServiceAdminId.migrations))

    _, res = await sanic_client.get("/api/data/platform/config")

    assert res.status_code == 200, res.text
    assert res.json is not None
    platform_config = res.json
    assert platform_config.get("incident_banner") == ""
    assert platform_config.get("etag") != ""


@pytest.mark.asyncio
async def test_patch_platform_config(
    sanic_client: SanicASGITestClient, admin_headers: dict[str, str], initialize_platform_config
) -> None:
    initial_config = await initialize_platform_config()

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
    sanic_client: SanicASGITestClient, user_headers: dict[str, str], initialize_platform_config
) -> None:
    initial_config = await initialize_platform_config()

    headers = merge_headers(user_headers, {"If-Match": initial_config["etag"]})
    payload = {"incident_banner": "Some content"}

    _, res = await sanic_client.patch("/api/data/platform/config", headers=headers, json=payload)

    assert res.status_code == 401, res.text
