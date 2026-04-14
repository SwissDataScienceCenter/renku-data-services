"""Tests for session secrets blueprint."""

from typing import TYPE_CHECKING

import pytest
from sanic_testing.testing import SanicASGITestClient

from renku_data_services import base_models
from renku_data_services.users.models import UserInfo

if TYPE_CHECKING:
    from renku_data_services.data_api.dependencies import DependencyManager


@pytest.mark.asyncio
async def test_post_internal_token_invalid_payload(sanic_client: SanicASGITestClient) -> None:
    _, response = await sanic_client.post("/api/data/internal/authentication/token")

    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_post_internal_token_valid_refresh_token(
    sanic_client: SanicASGITestClient, app_manager_instance: "DependencyManager", regular_user: UserInfo
) -> None:
    user = base_models.AuthenticatedAPIUser(
        id=regular_user.id,
        email=regular_user.email or "",
        access_token="",
        full_name=f"{regular_user.first_name} {regular_user.last_name}",
        first_name=regular_user.first_name,
        last_name=regular_user.last_name,
    )
    request_refresh_token = app_manager_instance.internal_token_mint.create_refresh_token(user=user, scope="test_scope")
    assert request_refresh_token != ""

    payload = {
        "grant_type": "refresh_token",
        "refresh_token": request_refresh_token,
    }
    _, response = await sanic_client.post("/api/data/internal/authentication/token", data=payload)

    assert response.status_code == 200, response.text
    assert isinstance(response.json, dict)
    result = response.json
    expected_keys = {
        "access_token",
        "token_type",
        "expires_in",
        "refresh_token",
        "refresh_expires_in",
        "scope",
    }
    assert set(result.keys()) == expected_keys
    assert isinstance(result.get("access_token"), str)
    assert result["access_token"] != ""
    assert result.get("token_type") == "Bearer"
    assert isinstance(result.get("expires_in"), int)
    assert result["expires_in"] == 900  # 900 seconds = 15 minutes
    assert isinstance(result.get("refresh_token"), str)
    assert result["refresh_token"] != ""
    assert isinstance(result.get("refresh_expires_in"), int)
    assert result["refresh_expires_in"] == 3600  # 3600 seconds = 1 hour
    assert result.get("scope") == "test_scope"

    # Check that the new access token is accepted by the internal authenticator
    new_access_token = result["access_token"]
    parsed_new_access_token = app_manager_instance.internal_authenticator._validate(new_access_token)
    assert parsed_new_access_token.get("sub") == regular_user.id
    assert parsed_new_access_token.get("email") == regular_user.email

    # Check that the new refresh token can be used again
    new_refresh_token = result["refresh_token"]
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": new_refresh_token,
    }
    _, response = await sanic_client.post("/api/data/internal/authentication/token", data=payload)
    assert response.status_code == 200, response.text
    assert isinstance(response.json, dict)
    assert isinstance(response.json.get("access_token"), str)
    assert response.json["access_token"] != ""
    assert response.json["access_token"] != new_access_token


@pytest.mark.asyncio
async def test_post_internal_token_reject_access_token(
    sanic_client: SanicASGITestClient, app_manager_instance: "DependencyManager", regular_user: UserInfo
) -> None:
    user = base_models.AuthenticatedAPIUser(
        id=regular_user.id,
        email=regular_user.email or "",
        access_token="",
        full_name=f"{regular_user.first_name} {regular_user.last_name}",
        first_name=regular_user.first_name,
        last_name=regular_user.last_name,
    )
    request_invalid_token = app_manager_instance.internal_token_mint.create_access_token(user=user, scope="test_scope")

    payload = {
        "grant_type": "refresh_token",
        "refresh_token": request_invalid_token,
    }
    _, response = await sanic_client.post("/api/data/internal/authentication/token", data=payload)

    assert response.status_code == 401, response.text
