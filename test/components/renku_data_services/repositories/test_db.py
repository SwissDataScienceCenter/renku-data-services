"""Tests for the db module."""

import uuid
from base64 import b64encode

import httpx
import pytest

from renku_data_services.base_models.core import AuthenticatedAPIUser
from renku_data_services.connected_services.models import (
    ConnectionStatus,
    OAuth2Client,
    ProviderKind,
    UnsavedOAuth2Client,
)
from renku_data_services.connected_services.orm import OAuth2ConnectionORM
from renku_data_services.data_api.dependencies import DependencyManager
from renku_data_services.migrations.core import run_migrations_for_app
from renku_data_services.repositories.db import GitRepositoriesRepository
from renku_data_services.repositories.models import (
    Metadata,
    ProviderConnection,
    ProviderData,
    RepositoryMetadataError,
)
from renku_data_services.users.models import UserInfo
from renku_data_services.utils import cryptography
from test.components.renku_data_services.connected_services.utils import (
    FixedOAuthHttpClientFactory,
    FixedTestOAuthHttpClient,
)
from test.components.renku_data_services.repositories import test_git_url

user = AuthenticatedAPIUser(
    id=str(uuid.uuid4()),
    access_token="abc",
    refresh_token="abc123",
    first_name="Repo",
    is_admin=True,
    email="admin@admin.com",
)


@pytest.mark.asyncio
async def test_get_repository_bad_url(app_manager_instance: DependencyManager) -> None:
    run_migrations_for_app("common")
    repo = app_manager_instance.git_repositories_repo

    for url in test_git_url.bad_urls:
        result = await repo.get_repository(url, user, None, user)
        assert result.error is not None
        print(result)


@pytest.mark.asyncio
async def test_get_repository_public_anon_url(app_manager_instance: DependencyManager) -> None:
    run_migrations_for_app("common")
    repo = app_manager_instance.git_repositories_repo

    url = "https://github.com/SwissDataScienceCenter/renku"
    result = await repo.get_repository(url, user, None, user)
    assert result.provider is None
    assert result.connection is None
    assert result.error is None
    assert isinstance(result.metadata, Metadata)
    assert result.metadata.pull_permission
    assert not result.metadata.push_permission
    assert result.metadata.git_url == url
    assert not result.metadata.web_url


@pytest.mark.asyncio
async def test_get_repository_with_provider(app_manager_instance: DependencyManager) -> None:
    run_migrations_for_app("common")
    (user, _) = await _make_user(app_manager_instance)
    repo = app_manager_instance.git_repositories_repo
    cc_repo = app_manager_instance.connected_services_repo
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

    url = "https://github.com/SwissDataScienceCenter/renku"
    result = await repo.get_repository(url, user, None, user)
    assert result.provider == ProviderData(id=provider.id, name=provider.display_name, url=provider.url)
    assert result.connection is None
    assert result.error is None
    assert isinstance(result.metadata, Metadata)
    assert result.metadata.git_url == url + ".git"
    assert result.metadata.web_url == url
    assert result.metadata.pull_permission
    assert not result.metadata.push_permission


@pytest.mark.asyncio
async def test_get_repository_with_pending_connection_public_repo(app_manager_instance: DependencyManager) -> None:
    run_migrations_for_app("common")
    (user, _) = await _make_user(app_manager_instance)
    repo = app_manager_instance.git_repositories_repo
    (provider, connOrm) = await _setup_connection(app_manager_instance, ConnectionStatus.pending)

    url = "https://github.com/SwissDataScienceCenter/renku"
    result = await repo.get_repository(url, user, None, user)
    assert result.provider
    assert result.provider.id == provider.id
    assert result.connection
    assert result.connection == ProviderConnection.fromORM(connOrm)
    assert result.error is None
    assert isinstance(result.metadata, Metadata)
    assert result.metadata.pull_permission
    assert not result.metadata.push_permission
    assert result.metadata.git_url == url + ".git"
    assert result.metadata.web_url == url


@pytest.mark.asyncio
async def test_get_repository_with_bad_token_public_repo(app_manager_instance: DependencyManager) -> None:
    run_migrations_for_app("common")
    (user, _) = await _make_user(app_manager_instance)
    repo = app_manager_instance.git_repositories_repo

    (provider, connOrm) = await _setup_connection(app_manager_instance, ConnectionStatus.connected)

    url = "https://github.com/SwissDataScienceCenter/renku"
    result = await repo.get_repository(url, user, None, user)
    assert result.provider
    assert result.provider.id == provider.id
    assert result.connection
    assert result.connection == ProviderConnection.fromORM(connOrm)
    assert result.error is None
    assert isinstance(result.metadata, Metadata)
    assert result.metadata.pull_permission
    assert not result.metadata.push_permission
    assert result.metadata.git_url == url + ".git"
    assert result.metadata.web_url == url


private_repo_url = "https://github.com/SwissDataScienceCenter/not-a-real-repo"


@pytest.mark.asyncio
async def test_get_repository_with_bad_metadata_response(app_manager_instance: DependencyManager) -> None:
    run_migrations_for_app("common")
    (user, _) = await _make_user(app_manager_instance)
    deps = app_manager_instance
    (provider, connOrm) = await _setup_connection(deps, ConnectionStatus.connected)

    bad_resp_client = FixedTestOAuthHttpClient(response=httpx.Response(status_code=200, json={}), client=provider)
    factory = FixedOAuthHttpClientFactory(
        deps.config.secrets.encryption_key, deps.config.db.async_session_maker, bad_resp_client
    )
    repo = GitRepositoriesRepository(deps.config.db.async_session_maker, factory, None, False)

    result = await repo.get_repository(private_repo_url, user, None, user)
    assert result.provider
    assert result.provider.id == provider.id
    assert result.connection
    assert result.connection == ProviderConnection.fromORM(connOrm)
    assert result.error == RepositoryMetadataError.metadata_validation
    assert not result.metadata


@pytest.mark.asyncio
async def test_get_repository_with_unauthorized_repo(app_manager_instance: DependencyManager) -> None:
    run_migrations_for_app("common")
    deps = app_manager_instance
    (user, _) = await _make_user(app_manager_instance)
    (provider, connOrm) = await _setup_connection(deps, ConnectionStatus.connected)

    bad_resp_client = FixedTestOAuthHttpClient(response=httpx.Response(status_code=401), client=provider)
    factory = FixedOAuthHttpClientFactory(
        deps.config.secrets.encryption_key, deps.config.db.async_session_maker, bad_resp_client
    )
    repo = GitRepositoriesRepository(deps.config.db.async_session_maker, factory, None, False)

    result = await repo.get_repository(private_repo_url, user, None, user)
    assert result.provider
    assert result.provider.id == provider.id
    assert result.connection
    assert result.connection == ProviderConnection.fromORM(connOrm)
    assert result.error == RepositoryMetadataError.metadata_unauthorized
    assert not result.metadata


# class ExpiredTokenOAuthClient(AsyncOAuth2Client):  # type: ignore[misc]
#     async def request(self, method, url, withhold_token=False, auth=httpx.USE_CLIENT_DEFAULT, **kwargs):
#         if self.token:
#             self.token["expires_at"] = time.time() - 5000
#             return await super().request(method, url, auth=auth, **kwargs)
#         else:
#             return await super().request(method, url, withhold_token=True, auth=auth, **kwargs)

#     async def _refresh_token(
#         self, url, refresh_token=None, body="", headers=None, auth=httpx._client.USE_CLIENT_DEFAULT, **kwargs
#     ):
#         raise OAuthError(
#             "invalid_grant",
#             (
#                 "The provided authorization grant is invalid, expired, revoked, does not match "
#                 "the redirection URI used in the authorization request, or was issued to another client."
#             ),
#         )

#     @asynccontextmanager
#     async def stream(self, method, url, withhold_token=False, auth=httpx._client.USE_CLIENT_DEFAULT, **kwargs):
#         if self.token:
#             self.token["expires_at"] = time.time() - 5000
#             async with super().stream(method, url, auth=auth, **kwargs) as resp:
#                 yield resp
#         else:
#             async with super().stream(method, url, withhold_token=True, auth=auth, **kwargs) as resp:
#                 yield resp

#     async def send(
#         self,
#         request: httpx.Request,
#         *,
#         stream: bool = False,
#         auth: httpx._types.AuthTypes | httpx._client.UseClientDefault | None = httpx.USE_CLIENT_DEFAULT,
#         follow_redirects: bool | httpx._client.UseClientDefault = httpx.USE_CLIENT_DEFAULT,
#     ) -> httpx.Response:
#         req_url = str(request.url)
#         if req_url == "https://api.github.com/repos/SwissDataScienceCenter/not-a-real-repo":
#             return httpx.Response(status_code=401, request=request)  # tried anonymously
#         elif req_url.endswith("/info/refs?service=git-upload-pack"):
#             return httpx.Response(status_code=404)
#         else:
#             raise Exception("stopping here")


# async def test_get_repository_expired_token(app_manager_instance: DependencyManager) -> None:
#     run_migrations_for_app("common")
#     deps = app_manager_instance
#     (user, _) = await _make_user(app_manager_instance)
#     cc_repo = ConnectedServicesRepository(
#         deps.config.db.async_session_maker, deps.config.secrets.encryption_key, ExpiredTokenOAuthClient
#     )
#     repo = GitRepositoriesRepository(
#         deps.config.db.async_session_maker, cc_repo, None, False, ExpiredTokenOAuthClient()
#     )

#     (provider, connOrm) = await _setup_connection(app_manager_instance, ConnectionStatus.connected)
#     result = await repo.get_repository(private_repo_url, user, None, user)
#     print(result)
#     assert result.provider
#     assert result.provider.id == provider.id
#     assert result.connection
#     assert result.connection == ProviderConnection.fromORM(connOrm)
#     assert result.error == RepositoryMetadataError.metadata_oauth
#     assert not result.metadata
# TODO: ^^


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
