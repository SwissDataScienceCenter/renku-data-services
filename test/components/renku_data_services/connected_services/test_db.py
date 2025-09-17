"""Testing db routines."""

from dataclasses import dataclass
from typing import cast

import pytest

from renku_data_services.base_models.core import APIUser
from renku_data_services.connected_services.db import ConnectedServicesRepository, Image
from renku_data_services.connected_services.models import (
    ConnectionStatus,
    OAuth2Client,
    ProviderKind,
    UnsavedOAuth2Client,
)
from renku_data_services.connected_services.orm import OAuth2ConnectionORM
from renku_data_services.data_api.dependencies import DependencyManager
from renku_data_services.migrations.core import run_migrations_for_app
from renku_data_services.users.db import UserRepo
from renku_data_services.users.models import UserInfo

github_image = Image.from_path("ghcr.io/sdsc/test")
gitlab_image = Image.from_path("registry.gitlab.com/sdsc/test")


@dataclass
class SetupData:
    admin: APIUser
    admin_info: UserInfo
    user1: APIUser
    user1_info: UserInfo
    user2: APIUser
    user2_info: UserInfo
    deps: DependencyManager

    @property
    def connected_repo(self) -> ConnectedServicesRepository:
        return self.deps.connected_services_repo

    async def insert_client(self, id: str, kind: ProviderKind, registry_url: str) -> OAuth2Client:
        c = UnsavedOAuth2Client(
            id=id,
            app_slug=f"{id}-slug",
            url=f"https://{id}.com",
            kind=kind,
            client_id="cid",
            client_secret="secret",
            display_name=f"{kind} {id}",
            scope="read:registry",
            use_pkce=False,
            image_registry_url=registry_url if registry_url != "" else None,
        )
        return await self.connected_repo.insert_oauth2_client(self.admin, c)

    async def connect(
        self, user: APIUser, provider_id: str, status: ConnectionStatus = ConnectionStatus.connected
    ) -> OAuth2ConnectionORM:
        repo = self.connected_repo
        provider = await repo.get_oauth2_client(provider_id, self.admin)

        async with self.deps.config.db.async_session_maker() as session, session.begin():
            if user.id is None:
                raise Exception(f"user {user} has no id")
            conn = OAuth2ConnectionORM(
                user_id=user.id,
                client_id=provider.id,
                token={"access_token": "bla"},
                status=status,
                state=None,
                code_verifier=None,
                next_url=None,
            )
            session.add(conn)
            return conn


async def setup_users(app_manager_instance: DependencyManager) -> SetupData:
    user_repo: UserRepo = app_manager_instance.kc_user_repo
    admin = APIUser(id="admin1", first_name="Ad", last_name="Min", is_admin=True, access_token="token_a")
    user1 = APIUser(id="id-123", first_name="Mads", last_name="Pedersen", access_token="token_u1")
    user2 = APIUser(id="id-234", first_name="Wout", last_name="van Art", access_token="token_u2")
    admin_info = cast(UserInfo, await user_repo.get_or_create_user(admin, str(admin.id)))
    user1_info = cast(UserInfo, await user_repo.get_or_create_user(user1, str(user1.id)))
    user2_info = cast(UserInfo, await user_repo.get_or_create_user(user2, str(user2.id)))
    return SetupData(admin, admin_info, user1, user1_info, user2, user2_info, app_manager_instance)


@pytest.mark.asyncio
async def test_get_provider_for_image_no_provider(app_manager_instance: DependencyManager) -> None:
    run_migrations_for_app("common")
    setup = await setup_users(app_manager_instance)
    db = setup.connected_repo
    p = await db.get_provider_for_image(setup.user1, github_image)
    assert p is None


@pytest.mark.asyncio
async def test_get_provider_for_image_no_connection(app_manager_instance) -> None:
    run_migrations_for_app("common")

    setup = await setup_users(app_manager_instance)
    await setup.insert_client("github", ProviderKind.github, "https://ghcr.io")

    p = await setup.connected_repo.get_provider_for_image(setup.user1, github_image)
    assert p is not None
    assert p.connected_user is None
    assert p.registry_url == "https://ghcr.io"
    assert p.provider.id == "github"


@pytest.mark.asyncio
async def test_get_provider_for_image_no_connection_for_user(app_manager_instance) -> None:
    run_migrations_for_app("common")

    setup = await setup_users(app_manager_instance)
    client = await setup.insert_client("github", ProviderKind.github, "https://ghcr.io")
    await setup.connect(setup.user1, client.id)

    p = await setup.connected_repo.get_provider_for_image(setup.user2, github_image)
    assert p is not None
    assert p.connected_user is None
    assert p.registry_url == "https://ghcr.io"
    assert p.provider.id == client.id


@pytest.mark.asyncio
async def test_get_provider_for_image_provider_with_connection(app_manager_instance) -> None:
    run_migrations_for_app("common")

    setup = await setup_users(app_manager_instance)
    client = await setup.insert_client("github", ProviderKind.github, "https://ghcr.io")
    await setup.connect(setup.user1, client.id)

    p = await setup.connected_repo.get_provider_for_image(setup.user1, github_image)
    assert p is not None
    assert p.connected_user is not None
    assert p.registry_url == "https://ghcr.io"
    assert p.provider.id == "github"
    assert p.connected_user.connection.status == ConnectionStatus.connected
    assert p.is_connected()


@pytest.mark.asyncio
async def test_get_provider_for_image_provider_with_pending_connection(app_manager_instance) -> None:
    run_migrations_for_app("common")

    setup = await setup_users(app_manager_instance)
    client = await setup.insert_client("github", ProviderKind.github, "https://ghcr.io")
    await setup.connect(setup.user1, client.id, ConnectionStatus.pending)

    p = await setup.connected_repo.get_provider_for_image(setup.user1, github_image)
    assert p is not None
    assert p.connected_user is not None
    assert p.registry_url == "https://ghcr.io"
    assert p.provider.id == "github"
    assert p.connected_user.connection.status == ConnectionStatus.pending
    assert not p.is_connected()


@pytest.mark.asyncio
async def test_get_provider_for_image_multiple_user(app_manager_instance) -> None:
    run_migrations_for_app("common")

    setup = await setup_users(app_manager_instance)
    client = await setup.insert_client("github", ProviderKind.github, "https://ghcr.io")
    conn1 = await setup.connect(setup.user1, client.id)
    await setup.connect(setup.user2, client.id)

    p = await setup.connected_repo.get_provider_for_image(setup.user1, github_image)
    assert p is not None
    assert p.connected_user is not None
    assert p.registry_url == "https://ghcr.io"
    assert p.provider.id == "github"
    assert p.connected_user.connection.id == conn1.id
    assert p.is_connected()


@pytest.mark.asyncio
async def test_get_provider_for_image_multiple_options(app_manager_instance) -> None:
    run_migrations_for_app("common")

    setup = await setup_users(app_manager_instance)
    client1 = await setup.insert_client("github1", ProviderKind.github, "https://ghcr.io")
    client2 = await setup.insert_client("github2", ProviderKind.github, "https://ghcr.io")
    await setup.connect(setup.user1, client1.id)
    conn2 = await setup.connect(setup.user1, client2.id)

    p = await setup.connected_repo.get_provider_for_image(setup.user1, github_image)
    assert p is not None
    assert p.connected_user is not None
    assert p.registry_url == "https://ghcr.io"
    assert p.provider.id == "github2"
    assert p.connected_user.connection.id == conn2.id
    assert p.is_connected()


@pytest.mark.asyncio
async def test_get_provider_for_image_no_registry_url(app_manager_instance) -> None:
    run_migrations_for_app("common")

    setup = await setup_users(app_manager_instance)
    await setup.insert_client("github", ProviderKind.github, "https://ghcr.io")

    p = await setup.connected_repo.get_provider_for_image(setup.user1, gitlab_image)
    assert p is None


@pytest.mark.asyncio
async def test_get_provider_for_image_unsupported_provider(app_manager_instance) -> None:
    run_migrations_for_app("common")

    setup = await setup_users(app_manager_instance)
    await setup.insert_client("google-drive", ProviderKind.drive, "")

    p = await setup.connected_repo.get_provider_for_image(setup.user1, gitlab_image)
    assert p is None


@pytest.mark.asyncio
async def test_delete_owned_connection(app_manager_instance: DependencyManager) -> None:
    run_migrations_for_app("common")

    setup = await setup_users(app_manager_instance)
    client = await setup.insert_client("github", ProviderKind.github, "https://ghcr.io")
    conn = await setup.connect(setup.user2, client.id)

    result = await setup.connected_repo.delete_oauth2_connection(setup.user2, str(conn.id))
    assert result


@pytest.mark.asyncio
async def test_not_delete_non_owned_connection(app_manager_instance: DependencyManager) -> None:
    run_migrations_for_app("common")

    setup = await setup_users(app_manager_instance)
    client = await setup.insert_client("github", ProviderKind.github, "https://ghcr.io")
    conn = await setup.connect(setup.user2, client.id)

    result = await setup.connected_repo.delete_oauth2_connection(setup.user1, str(conn.id))
    assert not result
