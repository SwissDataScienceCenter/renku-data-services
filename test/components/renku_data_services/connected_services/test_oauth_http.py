"""Tests for the oauth-http module."""

import uuid
from base64 import b64encode
from typing import Any

import pytest
from authlib.integrations.base_client import InvalidTokenError
from ulid import ULID

from renku_data_services.base_models.core import AuthenticatedAPIUser
from renku_data_services.connected_services.models import (
    ConnectionStatus,
    OAuth2Client,
    ProviderKind,
    UnsavedOAuth2Client,
)
from renku_data_services.connected_services.oauth_http import (
    DefaultOAuthHttpClientFactory,
    OAuthHttpFactoryError,
    _SafeAsyncOAuthClient,
)
from renku_data_services.connected_services.orm import OAuth2ConnectionORM
from renku_data_services.data_api.dependencies import DependencyManager
from renku_data_services.migrations.core import run_migrations_for_app
from renku_data_services.users.models import UserInfo
from renku_data_services.utils import cryptography

user = AuthenticatedAPIUser(
    id=str(uuid.uuid4()),
    access_token="abc",
    refresh_token="abc123",
    first_name="Repo",
    is_admin=True,
    email="admin@admin.com",
)


@pytest.mark.ayncio
async def test_create_client_invalid_connection(app_manager_instance: DependencyManager) -> None:
    run_migrations_for_app("common")
    deps = app_manager_instance
    (user, _) = await _make_user(deps)
    factory = DefaultOAuthHttpClientFactory(deps.config.secrets.encryption_key, deps.config.db.async_session_maker)

    (_, connOrm) = await _setup_connection(app_manager_instance, ConnectionStatus.pending)

    result = await factory.for_user_connection(user, connOrm.id)
    assert result == OAuthHttpFactoryError.invalid_connection


@pytest.mark.ayncio
async def test_create_client_no_connection(app_manager_instance: DependencyManager) -> None:
    run_migrations_for_app("common")
    deps = app_manager_instance
    (user, _) = await _make_user(deps)
    factory = DefaultOAuthHttpClientFactory(deps.config.secrets.encryption_key, deps.config.db.async_session_maker)

    result = await factory.for_user_connection(user, ULID())
    assert result == OAuthHttpFactoryError.invalid_connection


@pytest.mark.asyncio
async def test_create_client_success(app_manager_instance: DependencyManager) -> None:
    run_migrations_for_app("common")
    deps = app_manager_instance
    (user, _) = await _make_user(deps)
    factory = DefaultOAuthHttpClientFactory(deps.config.secrets.encryption_key, deps.config.db.async_session_maker)
    (client, conn) = await _setup_connection(deps, ConnectionStatus.connected)
    await factory.for_user_connection_raise(user, conn.id)


@pytest.mark.asyncio
async def test_lookup_token_on_error(app_manager_instance: DependencyManager) -> None:
    class BadTokenClient(_SafeAsyncOAuthClient):
        def _do_refresh_token(self, token: dict[str, Any]) -> None:
            raise InvalidTokenError()

    run_migrations_for_app("common")
    deps = app_manager_instance
    (user, _) = await _make_user(deps)
    factory = DefaultOAuthHttpClientFactory(deps.config.secrets.encryption_key, deps.config.db.async_session_maker)
    (client, conn) = await _setup_connection(deps, ConnectionStatus.connected)

    oauth_client = BadTokenClient(client.client_id, token={"expires_at": 1}, connection_id=conn.id, token_check=factory)

    await oauth_client.ensure_active_token({})
    assert oauth_client.token == {"expires_at": None, "access_token": "access_abc", "refresh_token": "refresh_abc"}


@pytest.mark.asyncio
async def test_store_new_token(app_manager_instance: DependencyManager) -> None:
    new_token = {"access_token": "access_xyz", "refresh_token": "refresh_xyz"}

    class TestTokenClient(_SafeAsyncOAuthClient):
        async def refresh_token(self, url=None, refresh_token=None, body: str = "", auth=None, headers=None, **kwargs):
            return new_token

    run_migrations_for_app("common")
    deps = app_manager_instance
    (user, _) = await _make_user(deps)
    factory = DefaultOAuthHttpClientFactory(deps.config.secrets.encryption_key, deps.config.db.async_session_maker)
    (client, conn) = await _setup_connection(deps, ConnectionStatus.connected)

    oauth_client = TestTokenClient(
        client.client_id,
        token={"expires_at": 1},
        connection_id=conn.id,
        token_check=factory,
        token_endpoint="https://some.url",
    )

    await oauth_client.ensure_active_token({"refresh_token": "yes"})
    async with deps.config.db.async_session_maker() as session:
        conn2 = await session.get_one(OAuth2ConnectionORM, conn.id)
        token = factory.decrypt_token_set(conn2.token or {}, user.id)
        assert token == new_token


async def _make_user(deps: DependencyManager) -> tuple[AuthenticatedAPIUser, UserInfo]:
    user_repo = deps.kc_user_repo
    u = await user_repo.get_or_create_user(user, user.id)
    assert u
    return (user, u)


async def _setup_connection(
    deps: DependencyManager, status: ConnectionStatus, expires_at: float | None = None
) -> tuple[OAuth2Client, OAuth2ConnectionORM]:
    run_migrations_for_app("common")
    (user, _) = await _make_user(deps)
    cc_repo = deps.connected_services_repo
    provider = await cc_repo.insert_oauth2_client(
        user,
        UnsavedOAuth2Client(
            id="prov1",
            app_slug="myapp",
            client_id="abc",
            client_secret="def",
            display_name="github",
            scope="api read",
            url="https://github.com",
            kind=ProviderKind.github,
            use_pkce=False,
        ),
    )

    access_token = b64encode(
        cryptography.encrypt_string(deps.config.secrets.encryption_key, user.id, "access_abc")
    ).decode("utf-8")
    refresh_token = b64encode(
        cryptography.encrypt_string(deps.config.secrets.encryption_key, user.id, "refresh_abc")
    ).decode("utf-8")

    async with deps.config.db.async_session_maker() as session, session.begin():
        connOrm = OAuth2ConnectionORM(
            user_id=user.id,
            client_id=provider.id,
            token={"access_token": access_token, "refresh_token": refresh_token, "expires_at": expires_at},
            state=None,
            status=status,
            code_verifier=None,
            next_url=None,
        )
        session.add(connOrm)
        await session.flush()
        await session.refresh(connOrm)

    return (provider, connOrm)
