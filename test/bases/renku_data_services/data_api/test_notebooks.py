"""Tests for notebook blueprints."""

import pytest
from sanic import Sanic
from sanic_testing.testing import SanicASGITestClient

from renku_data_services.app_config import Config
from renku_data_services.data_api.app import register_all_handlers


@pytest.fixture
def test_client(app_config: Config) -> SanicASGITestClient:
    app = Sanic(app_config.app_name)
    app = register_all_handlers(app, app_config)
    return SanicASGITestClient(app)


@pytest.mark.asyncio
@pytest.mark.parametrize("image,expected_status_code", [("python:3.12", 200), ("shouldnotexist:0.42", 404)])
async def test_check_docker_image(test_client: SanicASGITestClient, user_headers, image, expected_status_code):
    _, res = await test_client.get(f"/api/data/notebooks/images/?image_url={image}", headers=user_headers)

    assert res.status_code == expected_status_code, res.text
