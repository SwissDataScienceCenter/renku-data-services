import os
import secrets
import typing
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Self
from unittest.mock import MagicMock

from authzed.api.v1 import AsyncClient, SyncClient
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.types import PublicKeyTypes
from sanic import Request
from sanic_testing.testing import ASGI_HOST, ASGI_PORT, SanicASGITestClient, TestingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from yaml import safe_load

import renku_data_services.base_models as base_models
from renku_data_services import errors
from renku_data_services.app_config.config import (
    BuildsConfig,
    Config,
    PosthogConfig,
    SentryConfig,
    TrustedProxiesConfig,
)
from renku_data_services.app_config.server_options import (
    ServerOptions,
    ServerOptionsDefaults,
    generate_default_resource_pool,
)
from renku_data_services.authn.dummy import DummyAuthenticator, DummyUserStore
from renku_data_services.authz.authz import Authz
from renku_data_services.authz.config import AuthzConfig
from renku_data_services.base_models.metrics import MetricsService
from renku_data_services.crc import models as rp_models
from renku_data_services.crc.db import ResourcePoolRepository
from renku_data_services.db_config.config import DBConfig
from renku_data_services.git.gitlab import DummyGitlabAPI
from renku_data_services.k8s.clients import DummyCoreClient, DummySchedulingClient
from renku_data_services.k8s.quota import QuotaRepository
from renku_data_services.message_queue.config import RedisConfig
from renku_data_services.message_queue.redis_queue import RedisQueue
from renku_data_services.notebooks.config import NotebooksConfig
from renku_data_services.storage import models as storage_models
from renku_data_services.storage.db import StorageRepository
from renku_data_services.users import models as user_preferences_models
from renku_data_services.users.config import UserPreferencesConfig
from renku_data_services.users.db import UserPreferencesRepository
from renku_data_services.users.dummy_kc_api import DummyKeycloakAPI
from renku_data_services.users.kc_api import IKeycloakAPI


class StackSessionMaker:
    def __init__(self, parent: "DBConfigStack") -> None:
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
    def from_env(cls, prefix: str = "") -> Self:
        db = DBConfig.from_env(prefix)
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
    def from_env(cls, prefix: str = "") -> Self:
        config = AuthzConfig.from_env(prefix)
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
class TestAppConfig(Config):
    """Test class that can handle isolated dbs and authz instances."""

    @classmethod
    def from_env(cls, dummy_users: list[user_preferences_models.UnsavedUserInfo], prefix: str = "") -> "Config":
        """Create a config from environment variables."""

        user_store: base_models.UserStore
        authenticator: base_models.Authenticator
        gitlab_authenticator: base_models.Authenticator
        gitlab_client: base_models.GitlabAPIProtocol
        user_preferences_config: UserPreferencesConfig
        version = os.environ.get(f"{prefix}VERSION", "0.0.1")
        server_options_file = os.environ.get("SERVER_OPTIONS")
        server_defaults_file = os.environ.get("SERVER_DEFAULTS")
        k8s_namespace = os.environ.get("K8S_NAMESPACE", "default")
        max_pinned_projects = int(os.environ.get(f"{prefix}MAX_PINNED_PROJECTS", "10"))
        user_preferences_config = UserPreferencesConfig(max_pinned_projects=max_pinned_projects)
        db = DBConfigStack.from_env(prefix)
        kc_api: IKeycloakAPI
        secrets_service_public_key: PublicKeyTypes
        gitlab_url: str | None

        encryption_key = secrets.token_bytes(32)
        secrets_service_public_key_path = os.getenv(f"{prefix}SECRETS_SERVICE_PUBLIC_KEY_PATH")
        if secrets_service_public_key_path is not None:
            secrets_service_public_key = serialization.load_pem_public_key(
                Path(secrets_service_public_key_path).read_bytes()
            )
        else:
            private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            secrets_service_public_key = private_key.public_key()

        authenticator = DummyAuthenticator()
        gitlab_authenticator = DummyAuthenticator()
        quota_repo = QuotaRepository(DummyCoreClient({}, {}), DummySchedulingClient({}), namespace=k8s_namespace)
        user_always_exists = os.environ.get("DUMMY_USERSTORE_USER_ALWAYS_EXISTS", "true").lower() == "true"
        user_store = DummyUserStore(user_always_exists=user_always_exists)
        gitlab_client = DummyGitlabAPI()
        kc_api = DummyKeycloakAPI(users=[i.to_keycloak_dict() for i in dummy_users])
        redis = RedisConfig.fake()
        gitlab_url = None

        if not isinstance(secrets_service_public_key, rsa.RSAPublicKey):
            raise errors.ConfigurationError(message="Secret service public key is not an RSAPublicKey")

        sentry = SentryConfig.from_env(prefix)
        trusted_proxies = TrustedProxiesConfig.from_env(prefix)
        message_queue = RedisQueue(redis)
        nb_config = NotebooksConfig.from_env(db)
        builds_config = BuildsConfig.from_env(prefix)
        posthog = PosthogConfig.from_env(prefix)

        return cls(
            version=version,
            authenticator=authenticator,
            gitlab_authenticator=gitlab_authenticator,
            gitlab_client=gitlab_client,
            user_store=user_store,
            quota_repo=quota_repo,
            sentry=sentry,
            trusted_proxies=trusted_proxies,
            server_defaults_file=server_defaults_file,
            server_options_file=server_options_file,
            user_preferences_config=user_preferences_config,
            db=db,
            redis=redis,
            kc_api=kc_api,
            message_queue=message_queue,
            encryption_key=encryption_key,
            secrets_service_public_key=secrets_service_public_key,
            gitlab_url=gitlab_url,
            authz_config=AuthzConfigStack.from_env(),
            nb_config=nb_config,
            builds_config=builds_config,
            posthog=posthog,
        )

    def __post_init__(self) -> None:
        self.spec = self.load_apispec()

        if self.default_resource_pool_file is not None:
            with open(self.default_resource_pool_file) as f:
                self.default_resource_pool = rp_models.ResourcePool.from_dict(safe_load(f))
        if self.server_defaults_file is not None and self.server_options_file is not None:
            with open(self.server_options_file) as f:
                options = ServerOptions.model_validate(safe_load(f))
            with open(self.server_defaults_file) as f:
                defaults = ServerOptionsDefaults.model_validate(safe_load(f))
            self.default_resource_pool = generate_default_resource_pool(options, defaults)

        self.authz = NonCachingAuthz(self.authz_config)
        self._metrics_mock = MagicMock(spec=MetricsService)

    @property
    def metrics(self) -> MagicMock:
        return self._metrics_mock


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


def remove_id_from_quota(quota: rp_models.Quota) -> rp_models.Quota:
    kwargs = asdict(quota)
    kwargs["id"] = None
    return rp_models.Quota(**kwargs)


def remove_id_from_rc(rc: rp_models.ResourceClass) -> rp_models.ResourceClass:
    kwargs = asdict(rc)
    kwargs["id"] = None
    return rp_models.ResourceClass.from_dict(kwargs)


def remove_quota_from_rc(rc: rp_models.ResourceClass) -> rp_models.ResourceClass:
    return rc.update(quota=None)


def remove_id_from_rp(rp: rp_models.ResourcePool) -> rp_models.ResourcePool:
    quota = rp.quota
    if isinstance(quota, rp_models.Quota):
        quota = remove_id_from_quota(quota)
    classes = [remove_quota_from_rc(remove_id_from_rc(rc)) for rc in rp.classes]
    return rp_models.ResourcePool(
        name=rp.name,
        id=None,
        quota=quota,
        classes=classes,
        default=rp.default,
        public=rp.public,
        idle_threshold=rp.idle_threshold,
        hibernation_threshold=rp.hibernation_threshold,
    )


def remove_id_from_user(user: base_models.User) -> base_models.User:
    kwargs = asdict(user)
    kwargs["id"] = None
    return base_models.User(**kwargs)


def sort_rp_classes(classes: list[rp_models.ResourceClass]) -> list[rp_models.ResourceClass]:
    return sorted(classes, key=lambda c: (c.gpu, c.cpu, c.memory, c.max_storage, c.name))


async def create_rp(
    rp: rp_models.ResourcePool, repo: ResourcePoolRepository, api_user: base_models.APIUser
) -> rp_models.ResourcePool:
    inserted_rp = await repo.insert_resource_pool(api_user, rp)
    assert inserted_rp is not None
    assert inserted_rp.id is not None
    assert inserted_rp.quota is not None
    assert all([rc.id is not None for rc in inserted_rp.classes])
    inserted_rp_no_ids = remove_id_from_rp(inserted_rp)
    assert rp == inserted_rp_no_ids, f"resource pools do not match {rp} != {inserted_rp_no_ids}"
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
