"""Testing db routines."""

from dataclasses import dataclass
from typing import cast

import pytest

from test.utils import create_rp

from renku_data_services.base_models.core import APIUser
from renku_data_services.connected_services.db import ConnectedServicesRepository, Image
from renku_data_services.connected_services.models import (
    ConnectionStatus,
    OAuth2Client,
    ProviderKind,
    UnsavedOAuth2Client,
)
from renku_data_services.connected_services.orm import OAuth2ConnectionORM
from renku_data_services.crc import models as crc_models
from renku_data_services.crc.models import (
    MemberType,
    RemoteConfigurationFirecrest,
    ResourcePoolMemberIdentifier,
    RuntimePlatform,
)
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
    await setup.insert_client("google-drive", ProviderKind.dropbox, "")

    p = await setup.connected_repo.get_provider_for_image(setup.user1, gitlab_image)
    assert p is None


@pytest.mark.asyncio
async def test_oauth_connect_adds_user_to_rp(
    app_manager_instance: DependencyManager, admin_user: APIUser, cluster: any
) -> None:
    run_migrations_for_app("common")
    setup = await setup_users(app_manager_instance)

    provider_id = "test-provider-oauth-connect"
    client = await setup.insert_client(provider_id, ProviderKind.gitlab, "")

    # Create an RP linked to the provider
    rp = crc_models.UnsavedResourcePool(
        name="test-oauth-rp",
        classes=[],
        quota=crc_models.UnsavedQuota(cpu=1.0, memory=1, gpu=0),
        public=False,
        default=False,
        platform=RuntimePlatform.linux_amd64,
        remote=RemoteConfigurationFirecrest(
            provider_id=provider_id,
            api_url="https://example.org",
            system_name="test-system",
        ),
    )
    inserted_rp = await create_rp(rp, app_manager_instance.rp_repo, setup.admin)

    # Create a connection for user1
    async with app_manager_instance.config.db.async_session_maker() as session, session.begin():
        conn = OAuth2ConnectionORM(
            user_id=setup.user1.id,
            client_id=client.id,
            token={"access_token": "bla"},
            status=ConnectionStatus.connected,
            state=None,
            code_verifier=None,
            next_url=None,
        )
        session.add(conn)

    # Call _on_oauth2_connected directly
    await app_manager_instance.connected_services_repo._on_oauth2_connected(setup.user1.id, client.id)

    # Assert user1 is a viewer member of the RP
    members = await app_manager_instance.member_repo.get_resource_pool_members(setup.admin, inserted_rp.id)
    user_ids = {m.member_id for m in members if m.member_type == MemberType.USER}
    assert setup.user1.id in user_ids

    # Cleanup
    await app_manager_instance.rp_repo.delete_resource_pool(setup.admin, inserted_rp.id)


@pytest.mark.asyncio
async def test_oauth_disconnect_removes_user_from_rp(
    app_manager_instance: DependencyManager, admin_user: APIUser, cluster: any
) -> None:
    run_migrations_for_app("common")
    setup = await setup_users(app_manager_instance)

    provider_id = "test-provider-oauth-disconnect"
    client = await setup.insert_client(provider_id, ProviderKind.gitlab, "")

    # Create an RP linked to the provider
    rp = crc_models.UnsavedResourcePool(
        name="test-oauth-disconnect-rp",
        classes=[],
        quota=crc_models.UnsavedQuota(cpu=1.0, memory=1, gpu=0),
        public=False,
        default=False,
        platform=RuntimePlatform.linux_amd64,
        remote=RemoteConfigurationFirecrest(
            provider_id=provider_id,
            api_url="https://example.org",
            system_name="test-system",
        ),
    )
    inserted_rp = await create_rp(rp, app_manager_instance.rp_repo, setup.admin)

    # Create a connection and grant access
    async with app_manager_instance.config.db.async_session_maker() as session, session.begin():
        conn = OAuth2ConnectionORM(
            user_id=setup.user1.id,
            client_id=client.id,
            token={"access_token": "bla"},
            status=ConnectionStatus.connected,
            state=None,
            code_verifier=None,
            next_url=None,
        )
        session.add(conn)

    await app_manager_instance.connected_services_repo._on_oauth2_connected(setup.user1.id, client.id)

    # Verify user1 has access
    members = await app_manager_instance.member_repo.get_resource_pool_members(setup.admin, inserted_rp.id)
    user_ids = {m.member_id for m in members if m.member_type == MemberType.USER}
    assert setup.user1.id in user_ids

    # Disconnect user1
    await app_manager_instance.connected_services_repo._on_oauth2_disconnected(setup.user1.id, client.id)

    # Assert user1 is no longer a member
    members = await app_manager_instance.member_repo.get_resource_pool_members(setup.admin, inserted_rp.id)
    user_ids = {m.member_id for m in members if m.member_type == MemberType.USER}
    assert setup.user1.id not in user_ids

    # Cleanup
    await app_manager_instance.rp_repo.delete_resource_pool(setup.admin, inserted_rp.id)


@pytest.mark.asyncio
async def test_oauth_connect_with_no_matching_rp_does_nothing(
    app_manager_instance: DependencyManager, admin_user: APIUser
) -> None:
    run_migrations_for_app("common")
    setup = await setup_users(app_manager_instance)

    provider_id = "test-provider-no-match"
    client = await setup.insert_client(provider_id, ProviderKind.gitlab, "")

    # Create a connection for user1 but no RP linked to this provider
    async with app_manager_instance.config.db.async_session_maker() as session, session.begin():
        conn = OAuth2ConnectionORM(
            user_id=setup.user1.id,
            client_id=client.id,
            token={"access_token": "bla"},
            status=ConnectionStatus.connected,
            state=None,
            code_verifier=None,
            next_url=None,
        )
        session.add(conn)

    # This should not crash
    await app_manager_instance.connected_services_repo._on_oauth2_connected(setup.user1.id, client.id)

    # No RPs exist anyway so nothing to assert, just no crash


@pytest.mark.asyncio
async def test_two_users_connect_same_integration_both_get_access(
    app_manager_instance: DependencyManager, admin_user: APIUser, cluster: any
) -> None:
    run_migrations_for_app("common")
    setup = await setup_users(app_manager_instance)

    provider_id = "test-provider-two-users"
    client = await setup.insert_client(provider_id, ProviderKind.gitlab, "")

    # Create an RP linked to the provider
    rp = crc_models.UnsavedResourcePool(
        name="test-two-users-rp",
        classes=[],
        quota=crc_models.UnsavedQuota(cpu=1.0, memory=1, gpu=0),
        public=False,
        default=False,
        platform=RuntimePlatform.linux_amd64,
        remote=RemoteConfigurationFirecrest(
            provider_id=provider_id,
            api_url="https://example.org",
            system_name="test-system",
        ),
    )
    inserted_rp = await create_rp(rp, app_manager_instance.rp_repo, setup.admin)

    # Create connections for both users
    for user in [setup.user1, setup.user2]:
        async with app_manager_instance.config.db.async_session_maker() as session, session.begin():
            conn = OAuth2ConnectionORM(
                user_id=user.id,
                client_id=client.id,
                token={"access_token": "bla"},
                status=ConnectionStatus.connected,
                state=None,
                code_verifier=None,
                next_url=None,
            )
            session.add(conn)

    # Connect both users
    await app_manager_instance.connected_services_repo._on_oauth2_connected(setup.user1.id, client.id)
    await app_manager_instance.connected_services_repo._on_oauth2_connected(setup.user2.id, client.id)

    # Both should have access
    members = await app_manager_instance.member_repo.get_resource_pool_members(setup.admin, inserted_rp.id)
    user_ids = {m.member_id for m in members if m.member_type == MemberType.USER}
    assert setup.user1.id in user_ids
    assert setup.user2.id in user_ids

    # Cleanup
    await app_manager_instance.rp_repo.delete_resource_pool(setup.admin, inserted_rp.id)


@pytest.mark.asyncio
async def test_user_disconnect_only_affects_their_rp_access(
    app_manager_instance: DependencyManager, admin_user: APIUser, cluster: any
) -> None:
    run_migrations_for_app("common")
    setup = await setup_users(app_manager_instance)

    provider_id = "test-provider-isolated-disconnect"
    client = await setup.insert_client(provider_id, ProviderKind.gitlab, "")

    # Create an RP linked to the provider
    rp = crc_models.UnsavedResourcePool(
        name="test-isolated-rp",
        classes=[],
        quota=crc_models.UnsavedQuota(cpu=1.0, memory=1, gpu=0),
        public=False,
        default=False,
        platform=RuntimePlatform.linux_amd64,
        remote=RemoteConfigurationFirecrest(
            provider_id=provider_id,
            api_url="https://example.org",
            system_name="test-system",
        ),
    )
    inserted_rp = await create_rp(rp, app_manager_instance.rp_repo, setup.admin)

    # Create connections for both users
    for user in [setup.user1, setup.user2]:
        async with app_manager_instance.config.db.async_session_maker() as session, session.begin():
            conn = OAuth2ConnectionORM(
                user_id=user.id,
                client_id=client.id,
                token={"access_token": "bla"},
                status=ConnectionStatus.connected,
                state=None,
                code_verifier=None,
                next_url=None,
            )
            session.add(conn)

    # Grant both users
    await app_manager_instance.connected_services_repo._on_oauth2_connected(setup.user1.id, client.id)
    await app_manager_instance.connected_services_repo._on_oauth2_connected(setup.user2.id, client.id)

    # Disconnect user1 only
    await app_manager_instance.connected_services_repo._on_oauth2_disconnected(setup.user1.id, client.id)

    # user1 revoked, user2 still has access
    members = await app_manager_instance.member_repo.get_resource_pool_members(setup.admin, inserted_rp.id)
    user_ids = {m.member_id for m in members if m.member_type == MemberType.USER}
    assert setup.user1.id not in user_ids
    assert setup.user2.id in user_ids

    # Cleanup
    await app_manager_instance.rp_repo.delete_resource_pool(setup.admin, inserted_rp.id)


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
