"""Tests for the db module."""

import uuid

import pytest

from renku_data_services.base_models.core import AuthenticatedAPIUser
from renku_data_services.connected_services.models import ConnectionStatus, ProviderKind, UnsavedOAuth2Client
from renku_data_services.connected_services.orm import OAuth2ConnectionORM
from renku_data_services.data_api.dependencies import DependencyManager
from renku_data_services.migrations.core import run_migrations_for_app
from renku_data_services.repositories.models import Metadata, ProviderData
from renku_data_services.users.models import UserInfo
from test.components.renku_data_services.repositories import test_git_url

# - check url string
# - find provider in db (can't be done via a query (easily), must load all and filter)
# - NO client found:
#   - check internal gitlab OR
#   - check if url is a git repository -> result
# - YES client found:
#  - find connection for user and provider
#  - get repo metadata with or without the connection (here we can use if-none-match)

user = AuthenticatedAPIUser(id=str(uuid.uuid4()), access_token="abc", first_name="Repo", is_admin=True)


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
    print(result)


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
    print(result)


@pytest.mark.asyncio
async def test_get_repository_with_pending_connection(app_manager_instance: DependencyManager) -> None:
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
    async with app_manager_instance.config.db.async_session_maker() as session, session.begin():
        connOrm = OAuth2ConnectionORM(
            user_id=user.id,
            client_id=provider.id,
            token={"access_token": "test"},
            state=None,
            status=ConnectionStatus.pending,
            code_verifier=None,
            next_url=None
        )
        session.add(connOrm)
        await session.flush()
        await session.refresh(connOrm)



async def _make_user(deps: DependencyManager) -> tuple[AuthenticatedAPIUser, UserInfo]:
    user_repo = deps.kc_user_repo
    u = await user_repo.get_or_create_user(user, user.id)
    assert u
    return (user, u)
