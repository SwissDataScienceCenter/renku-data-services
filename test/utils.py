from __future__ import annotations

import os
import typing
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any, Self
from unittest.mock import MagicMock

from authzed.api.v1 import AsyncClient, SyncClient
from sanic import Request
from sanic_testing.testing import ASGI_HOST, ASGI_PORT, SanicASGITestClient, TestingResponse
from sqlalchemy.ext.asyncio import AsyncSession

import renku_data_services.base_models as base_models
from renku_data_services.authn.dummy import DummyAuthenticator, DummyUserStore
from renku_data_services.authz.authz import Authz
from renku_data_services.authz.config import AuthzConfig
from renku_data_services.base_models.metrics import MetricsService
from renku_data_services.connected_services.db import ConnectedServicesRepository
from renku_data_services.crc import models as rp_models
from renku_data_services.crc.db import ClusterRepository, ResourcePoolRepository, UserRepository
from renku_data_services.data_api.config import Config
from renku_data_services.data_api.dependencies import DependencyManager
from renku_data_services.data_connectors.db import DataConnectorRepository, DataConnectorSecretRepository
from renku_data_services.db_config.config import DBConfig
from renku_data_services.git.gitlab import DummyGitlabAPI
from renku_data_services.k8s.clients import DummyCoreClient, DummySchedulingClient
from renku_data_services.k8s.db import QuotaRepository
from renku_data_services.message_queue.db import ReprovisioningRepository
from renku_data_services.metrics.db import MetricsRepository
from renku_data_services.namespace.db import GroupRepository
from renku_data_services.notebooks.api.classes.data_service import GitProviderHelper
from renku_data_services.notifications.db import NotificationsRepository
from renku_data_services.platform.db import PlatformRepository, UrlRedirectRepository
from renku_data_services.project.db import (
    ProjectMemberRepository,
    ProjectMigrationRepository,
    ProjectRepository,
    ProjectSessionSecretRepository,
)
from renku_data_services.repositories.db import GitRepositoriesRepository
from renku_data_services.search.db import SearchUpdatesRepo
from renku_data_services.search.reprovision import SearchReprovision
from renku_data_services.secrets.db import LowLevelUserSecretsRepo, UserSecretsRepo
from renku_data_services.session.db import SessionRepository
from renku_data_services.storage import models as storage_models
from renku_data_services.storage.db import StorageRepository
from renku_data_services.users import models as user_preferences_models
from renku_data_services.users.db import UserPreferencesRepository
from renku_data_services.users.db import UserRepo as KcUserRepo
from renku_data_services.users.dummy_kc_api import DummyKeycloakAPI
from renku_data_services.users.kc_api import IKeycloakAPI


class StackSessionMaker:
    def __init__(self, parent: DBConfigStack) -> None:
        self.parent = parent

    def __call__(self, *args: Any, **kwds: Any) -> AsyncSession:
        return self.parent.current.async_session_maker()


class DBConfigStack:
    stack: list[DBConfig] = list()

    @property
    def current(self) -> DBConfig:
        return self.stack[-1]

    @property
    def password(self) -> str:
        return self.current.password

    @property
    def host(self) -> str:
        return self.current.host

    @property
    def user(self) -> str:
        return self.current.user

    @property
    def port(self) -> str:
        return self.current.port

    @property
    def db_name(self) -> str:
        return self.current.db_name

    def conn_url(self, async_client: bool = True) -> str:
        return self.current.conn_url(async_client)

    @property
    def async_session_maker(self) -> Callable[..., AsyncSession]:
        return StackSessionMaker(self)

    @classmethod
    def from_env(cls) -> Self:
        db = DBConfig.from_env()
        this = cls()
        this.push(db)
        return this

    def push(self, config: DBConfig) -> None:
        self.stack.append(config)

    async def pop(self) -> DBConfig:
        config = self.stack.pop()
        await DBConfig.dispose_connection()
        return config


class AuthzConfigStack:
    stack: list[AuthzConfig] = list()

    @property
    def host(self) -> str:
        return self.current.host

    @property
    def grpc_port(self) -> int:
        return self.current.grpc_port

    @property
    def key(self) -> str:
        return self.current.key

    @property
    def no_tls_connection(self) -> bool:
        return self.current.no_tls_connection

    @property
    def current(self) -> AuthzConfig:
        return self.stack[-1]

    @classmethod
    def from_env(cls) -> Self:
        config = AuthzConfig.from_env()
        this = cls()
        this.push(config)
        return this

    def authz_client(self) -> SyncClient:
        return self.current.authz_client()

    def authz_async_client(self) -> AsyncClient:
        return self.current.authz_async_client()

    def push(self, config: AuthzConfig):
        self.stack.append(config)

    def pop(self) -> AuthzConfig:
        return self.stack.pop()


@dataclass
class NonCachingAuthz(Authz):
    @property
    def client(self) -> AsyncClient:
        return self.authz_config.authz_async_client()


@dataclass
class TestDependencyManager(DependencyManager):
    """Test class that can handle isolated dbs and authz instances."""

    @classmethod
    def from_env(
        cls, dummy_users: list[user_preferences_models.UnsavedUserInfo], prefix: str = ""
    ) -> DependencyManager:
        """Create a config from environment variables."""
        db = DBConfigStack.from_env()
        config = Config.from_env(db)
        user_store: base_models.UserStore
        authenticator: base_models.Authenticator
        gitlab_authenticator: base_models.Authenticator
        gitlab_client: base_models.GitlabAPIProtocol
        k8s_namespace = os.environ.get("K8S_NAMESPACE", "default")
        config.authz_config = AuthzConfigStack.from_env()
        kc_api: IKeycloakAPI

        authenticator = DummyAuthenticator()
        gitlab_authenticator = DummyAuthenticator()
        quota_repo = QuotaRepository(DummyCoreClient({}, {}), DummySchedulingClient({}), namespace=k8s_namespace)
        user_always_exists = os.environ.get("DUMMY_USERSTORE_USER_ALWAYS_EXISTS", "true").lower() == "true"
        user_store = DummyUserStore(user_always_exists=user_always_exists)
        gitlab_client = DummyGitlabAPI()
        kc_api = DummyKeycloakAPI(users=[i.to_keycloak_dict() for i in dummy_users])

        authz = NonCachingAuthz(config.authz_config)
        search_updates_repo = SearchUpdatesRepo(session_maker=config.db.async_session_maker)
        metrics_mock = MagicMock(spec=MetricsService)
        group_repo = GroupRepository(
            session_maker=config.db.async_session_maker,
            group_authz=authz,
            search_updates_repo=search_updates_repo,
        )
        kc_user_repo = KcUserRepo(
            session_maker=config.db.async_session_maker,
            group_repo=group_repo,
            search_updates_repo=search_updates_repo,
            encryption_key=config.secrets.encryption_key,
            metrics=metrics_mock,
            authz=authz,
        )

        user_repo = UserRepository(
            session_maker=config.db.async_session_maker,
            quotas_repo=quota_repo,
            user_repo=kc_user_repo,
        )
        rp_repo = ResourcePoolRepository(session_maker=config.db.async_session_maker, quotas_repo=quota_repo)
        storage_repo = StorageRepository(
            session_maker=config.db.async_session_maker,
            gitlab_client=gitlab_client,
            user_repo=kc_user_repo,
            secret_service_public_key=config.secrets.public_key,
        )
        reprovisioning_repo = ReprovisioningRepository(session_maker=config.db.async_session_maker)
        project_repo = ProjectRepository(
            session_maker=config.db.async_session_maker,
            authz=authz,
            group_repo=group_repo,
            search_updates_repo=search_updates_repo,
        )
        session_repo = SessionRepository(
            session_maker=config.db.async_session_maker,
            project_authz=authz,
            resource_pools=rp_repo,
            shipwright_client=None,
            builds_config=config.builds,
        )
        project_migration_repo = ProjectMigrationRepository(
            session_maker=config.db.async_session_maker,
            authz=authz,
            project_repo=project_repo,
            session_repo=session_repo,
        )
        project_member_repo = ProjectMemberRepository(
            session_maker=config.db.async_session_maker,
            authz=authz,
        )
        project_session_secret_repo = ProjectSessionSecretRepository(
            session_maker=config.db.async_session_maker,
            authz=authz,
            user_repo=kc_user_repo,
            secret_service_public_key=config.secrets.public_key,
        )
        user_preferences_repo = UserPreferencesRepository(
            session_maker=config.db.async_session_maker,
            user_preferences_config=config.user_preferences,
        )
        low_level_user_secrets_repo = LowLevelUserSecretsRepo(
            session_maker=config.db.async_session_maker,
        )
        user_secrets_repo = UserSecretsRepo(
            session_maker=config.db.async_session_maker,
            low_level_repo=low_level_user_secrets_repo,
            user_repo=kc_user_repo,
            secret_service_public_key=config.secrets.public_key,
        )
        connected_services_repo = ConnectedServicesRepository(
            session_maker=config.db.async_session_maker,
            encryption_key=config.secrets.encryption_key,
            async_oauth2_client_class=cls.async_oauth2_client_class,
        )
        git_repositories_repo = GitRepositoriesRepository(
            session_maker=config.db.async_session_maker,
            connected_services_repo=connected_services_repo,
            internal_gitlab_url=config.gitlab_url,
            enable_internal_gitlab=config.enable_internal_gitlab,
        )
        platform_repo = PlatformRepository(
            session_maker=config.db.async_session_maker,
        )
        url_redirect_repo = UrlRedirectRepository(session_maker=config.db.async_session_maker, authz=authz)
        data_connector_repo = DataConnectorRepository(
            session_maker=config.db.async_session_maker,
            authz=authz,
            project_repo=project_repo,
            group_repo=group_repo,
            search_updates_repo=search_updates_repo,
        )
        data_connector_secret_repo = DataConnectorSecretRepository(
            session_maker=config.db.async_session_maker,
            data_connector_repo=data_connector_repo,
            user_repo=kc_user_repo,
            secret_service_public_key=config.secrets.public_key,
            authz=authz,
        )
        search_reprovisioning = SearchReprovision(
            search_updates_repo=search_updates_repo,
            reprovisioning_repo=reprovisioning_repo,
            solr_config=config.solr,
            user_repo=kc_user_repo,
            group_repo=group_repo,
            project_repo=project_repo,
            data_connector_repo=data_connector_repo,
        )
        cluster_repo = ClusterRepository(session_maker=config.db.async_session_maker)
        metrics_repo = MetricsRepository(session_maker=config.db.async_session_maker)
        notifications_repo = NotificationsRepository(session_maker=config.db.async_session_maker)
        git_provider_helper = GitProviderHelper(connected_services_repo, "", "", "", config.enable_internal_gitlab)
        return cls(
            config=config,
            authenticator=authenticator,
            gitlab_authenticator=gitlab_authenticator,
            gitlab_client=gitlab_client,
            user_store=user_store,
            quota_repo=quota_repo,
            kc_api=kc_api,
            user_repo=user_repo,
            rp_repo=rp_repo,
            storage_repo=storage_repo,
            reprovisioning_repo=reprovisioning_repo,
            search_updates_repo=search_updates_repo,
            search_reprovisioning=search_reprovisioning,
            project_repo=project_repo,
            project_migration_repo=project_migration_repo,
            project_member_repo=project_member_repo,
            project_session_secret_repo=project_session_secret_repo,
            group_repo=group_repo,
            session_repo=session_repo,
            user_preferences_repo=user_preferences_repo,
            kc_user_repo=kc_user_repo,
            user_secrets_repo=user_secrets_repo,
            connected_services_repo=connected_services_repo,
            git_repositories_repo=git_repositories_repo,
            platform_repo=platform_repo,
            data_connector_repo=data_connector_repo,
            data_connector_secret_repo=data_connector_secret_repo,
            cluster_repo=cluster_repo,
            metrics_repo=metrics_repo,
            metrics=metrics_mock,
            shipwright_client=None,
            authz=authz,
            low_level_user_secrets_repo=low_level_user_secrets_repo,
            url_redirect_repo=url_redirect_repo,
            git_provider_helper=git_provider_helper,
            notifications_repo=notifications_repo,
        )

    def __post_init__(self) -> None:
        self.spec = self.load_apispec()


class SanicReusableASGITestClient(SanicASGITestClient):
    """Reusable async test client for sanic.

    Sanic has 3 test clients, SanicTestClient (sync), SanicASGITestClient (async) and ReusableClient (sync).
    The first two will drop all routes and server state before each request (!) and calculate all routes
    again and execute server start code again (!), whereas the latter only does that once per client, but
    isn't async. This can cost as much as 40% of test execution time.
    This class is essentially a combination of SanicASGITestClient and ReusableClient.
    """

    set_up = False

    async def __aenter__(self):
        await self.run()
        return self

    async def __aexit__(self, *_):
        await self.stop()

    async def run(self):
        self.sanic_app.router.reset()
        self.sanic_app.signal_router.reset()
        await self.sanic_app._startup()  # type: ignore
        await self.sanic_app._server_event("init", "before")
        await self.sanic_app._server_event("init", "after")
        for route in self.sanic_app.router.routes:
            if self._collect_request not in route.extra.request_middleware:
                route.extra.request_middleware.appendleft(self._collect_request)
        if self._collect_request not in self.sanic_app.request_middleware:
            self.sanic_app.request_middleware.appendleft(
                self._collect_request  # type: ignore
            )
        self.set_up = True

    async def stop(self):
        self.set_up = False
        try:
            await self.sanic_app._server_event("shutdown", "before")
            await self.sanic_app._server_event("shutdown", "after")
        except:  # noqa: E722
            # NOTE: there are some race conditions in sanic when stopping that can cause errors. We ignore errors
            # here as otherwise failures in teardown can cause other session scoped fixtures to fail
            pass

    async def request(  # type: ignore
        self, method, url, gather_request=True, *args, **kwargs
    ) -> tuple[typing.Optional[Request], typing.Optional[TestingResponse]]:
        if not self.set_up:
            raise RuntimeError(
                "Trying to call request without first entering context manager. Only use this class in a `with` block"
            )

        if not url.startswith(("http:", "https:", "ftp:", "ftps://", "//", "ws:", "wss:")):
            url = url if url.startswith("/") else f"/{url}"
            scheme = "ws" if method == "websocket" else "http"
            url = f"{scheme}://{ASGI_HOST}:{ASGI_PORT}{url}"

        self.gather_request = gather_request
        if self.sanic_app.router.find_route is None:
            # sometimes routes get deleted during test execution for an unknown reason. restarting the server fixes this
            await self.stop()
            await self.run()
        # call SanicASGITestClient's parent request method
        response = await super(SanicASGITestClient, self).request(method, url, *args, **kwargs)

        response.__class__ = TestingResponse

        if gather_request:
            return self.last_request, response  # type: ignore
        return None, response  # type: ignore


def remove_id_from_rc(rc: rp_models.ResourceClass) -> rp_models.ResourceClass:
    kwargs = asdict(rc)
    kwargs["id"] = None
    return rp_models.ResourceClass.from_dict(kwargs)


def remove_quota_from_rc(rc: rp_models.ResourceClass) -> rp_models.ResourceClass:
    return rc.update(quota={})


def remove_id_from_user(user: base_models.User) -> base_models.User:
    kwargs = asdict(user)
    kwargs["id"] = None
    return base_models.User(**kwargs)


def sort_rp_classes(classes: list[rp_models.ResourceClass]) -> list[rp_models.ResourceClass]:
    return sorted(classes, key=lambda c: (c.gpu, c.cpu, c.memory, c.max_storage, c.name))


async def create_rp(
    rp: rp_models.UnsavedResourcePool, repo: ResourcePoolRepository, api_user: base_models.APIUser
) -> rp_models.ResourcePool:
    inserted_rp = await repo.insert_resource_pool(api_user, rp)

    assert inserted_rp is not None
    assert inserted_rp.id is not None
    assert inserted_rp.quota is not None
    assert all([rc.id is not None for rc in inserted_rp.classes])
    retrieved_rps = await repo.get_resource_pools(api_user, inserted_rp.id)
    assert len(retrieved_rps) == 1
    assert inserted_rp.id == retrieved_rps[0].id
    assert inserted_rp.name == retrieved_rps[0].name
    assert inserted_rp.idle_threshold == retrieved_rps[0].idle_threshold
    assert sort_rp_classes(inserted_rp.classes) == sort_rp_classes(retrieved_rps[0].classes)
    assert inserted_rp.quota == retrieved_rps[0].quota
    return inserted_rp


async def create_storage(storage_dict: dict[str, Any], repo: StorageRepository, user: base_models.APIUser):
    storage_dict["configuration"] = storage_models.RCloneConfig.model_validate(storage_dict["configuration"])
    storage = storage_models.CloudStorage.model_validate(storage_dict)

    inserted_storage = await repo.insert_storage(storage, user=user)
    assert inserted_storage is not None
    assert inserted_storage.storage_id is not None
    retrieved_storage = await repo.get_storage_by_id(inserted_storage.storage_id, user=user)
    assert retrieved_storage is not None

    assert inserted_storage.model_dump() == retrieved_storage.model_dump()
    return inserted_storage


async def create_user_preferences(
    project_slug: str, repo: UserPreferencesRepository, user: base_models.APIUser
) -> user_preferences_models.UserPreferences:
    """Create user preferencers by adding a pinned project"""
    user_preferences = await repo.add_pinned_project(requested_by=user, project_slug=project_slug)
    assert user_preferences is not None
    assert user_preferences.user_id is not None
    assert user_preferences.pinned_projects is not None
    assert project_slug in user_preferences.pinned_projects.project_slugs

    return user_preferences
