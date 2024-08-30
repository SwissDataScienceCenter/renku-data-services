"""Tests for notebook blueprints."""

import pytest
from pytest_httpx import HTTPXMock
from sanic_testing.testing import SanicASGITestClient


@pytest.fixture
def non_mocked_hosts() -> list:
    """Hosts that should not get mocked during tests."""

    return ["127.0.0.1"]


@pytest.mark.asyncio
@pytest.mark.parametrize("image,expected_status_code", [("python:3.12", 200), ("shouldnotexist:0.42", 404)])
async def test_check_docker_image(sanic_client: SanicASGITestClient, user_headers, image, expected_status_code):
    """Validate that the images endpoint answers correctly."""

    _, res = await sanic_client.get(f"/api/data/notebooks/images/?image_url={image}", headers=user_headers)

    assert res.status_code == expected_status_code, res.text


@pytest.mark.asyncio
@pytest.mark.parametrize("server_name,expected_status_code", [("unknown", 404)])
async def test_log_retrieval(
    sanic_client: SanicASGITestClient, httpx_mock: HTTPXMock, user_headers, server_name, expected_status_code
):
    """Validate that the logs endpoint answers correctly"""

    httpx_mock.add_response(url=f"http://not.specified/servers/{server_name}", json={}, status_code=200)

    _, res = await sanic_client.get(f"/api/data/notebooks/logs/{server_name}", headers=user_headers)

    assert res.status_code == expected_status_code, res.text
