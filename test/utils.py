from __future__ import annotations

import base64
import json
import os
import subprocess
import typing
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Self
from unittest.mock import MagicMock

import yaml
from authzed.api.v1 import AsyncClient, SyncClient
from kubernetes import client as k8s_client
from kubernetes import config as k8s_config
from kubernetes import watch
from kubernetes.client import V1ObjectMeta
from sanic import Request
from sanic_testing.testing import ASGI_HOST, ASGI_PORT, SanicASGITestClient, TestingResponse
from sqlalchemy.ext.asyncio import AsyncSession

import renku_data_services.base_models as base_models
from renku_data_services.authn.dummy import DummyAuthenticator, DummyUserStore
from renku_data_services.authz.authz import Authz
from renku_data_services.authz.config import AuthzConfig
from renku_data_services.base_models.metrics import MetricsService
from renku_data_services.capacity_reservation.db import CapacityReservationRepository, OccurrenceRepository
from renku_data_services.connected_services.db import ConnectedServicesRepository
from renku_data_services.connected_services.oauth_http import DefaultOAuthHttpClientFactory
from renku_data_services.crc import models as rp_models
from renku_data_services.crc.db import ClusterRepository, QuotaRepository, ResourcePoolRepository, UserRepository
from renku_data_services.data_api.config import Config
from renku_data_services.data_api.dependencies import DependencyManager
from renku_data_services.data_connectors.db import DataConnectorRepository, DataConnectorSecretRepository
from renku_data_services.data_connectors.deposits.zenodo import ZenodoAPIClient
from renku_data_services.db_config.config import DBConfig
from renku_data_services.git.gitlab import DummyGitlabAPI
from renku_data_services.k8s.clients import (
    DepositUploadJobClient,
    K8sClusterClientsPool,
    K8sPriorityClassClient,
    K8sResourceQuotaClient,
    K8sSecretClient,
)
from renku_data_services.k8s.config import KubeConfigEnv, get_clusters
from renku_data_services.k8s.db import K8sDbCache
from renku_data_services.message_queue.db import ReprovisioningRepository
from renku_data_services.metrics.db import MetricsRepository
from renku_data_services.namespace.db import GroupRepository
from renku_data_services.notebooks.api.classes.data_service import GitProviderHelper
from renku_data_services.notebooks.constants import AMALTHEA_SESSION_GVK, JUPYTER_SESSION_GVK
from renku_data_services.notebooks.data_sources import DataSourceRepository
from renku_data_services.notebooks.image_check import ImageCheckRepository
from renku_data_services.notifications.db import NotificationsRepository
from renku_data_services.platform.db import PlatformRepository, UrlRedirectRepository
from renku_data_services.project.db import (
    ProjectMemberRepository,
    ProjectMigrationRepository,
    ProjectRepository,
    ProjectSessionSecretRepository,
)
from renku_data_services.repositories import models as repositories_models
from renku_data_services.repositories.db import GitRepositoriesRepository
from renku_data_services.repositories.git_url import GitUrl, GitUrlError
from renku_data_services.resource_usage.core import ResourceUsageService
from renku_data_services.resource_usage.db import ResourceRequestsRepo
from renku_data_services.search.db import SearchUpdatesRepo
from renku_data_services.search.reprovision import SearchReprovision
from renku_data_services.secrets.db import LowLevelUserSecretsRepo, UserSecretsRepo
from renku_data_services.session.constants import BUILD_RUN_GVK, TASK_RUN_GVK
from renku_data_services.session.db import SessionRepository
from renku_data_services.session.k8s_client import ShipwrightClient
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


class FakeGitRepositoriesRepository(GitRepositoriesRepository):
    """Test class to simulate repository visibility checks and token retrieval"""

    async def get_token(self, repository_url, user) -> dict[str, Any] | None:
        """Get token for repository provider."""
        return {"access_token": "dummy token"}

    async def get_repository(
        self,
        repository_url,
        user,
        etag,
        internal_gitlab_user,
    ) -> repositories_models.RepositoryDataResult:
        """Get metadata about one repository."""

        match GitUrl.parse(repository_url):
            case GitUrlError() as err:
                return repositories_models.RepositoryDataResult(error=err)
            case url:
                valid_url = url
                result = repositories_models.RepositoryDataResult()

        match valid_url.parsed_url.path:
            case "/SwissDataScienceCenter/renku":
                result = result.with_metadata(
                    repositories_models.Metadata(
                        git_url=valid_url.render(),
                        pull_permission=True,
                        visibility=repositories_models.RepositoryVisibility.public,
                    )
                )
            case "/SwissDataScienceCenter/private":
                result = result.with_metadata(
                    repositories_models.Metadata(
                        git_url=valid_url.render(),
                        pull_permission=True,
                        visibility=repositories_models.RepositoryVisibility.private,
                    )
                )
            case "/SwissDataScienceCenter/other-private":
                result = result.with_metadata(
                    repositories_models.Metadata(
                        git_url=valid_url.render(),
                        pull_permission=False,
                        visibility=repositories_models.RepositoryVisibility.private,
                    )
                )
            case "/some/repo":
                result = result.with_error(GitUrlError.no_git_repo)
            case _:
                result = await super().get_repository(repository_url, user, etag, internal_gitlab_user)

        return result


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
        config.authz_config = AuthzConfigStack.from_env()
        nb_authz = NonCachingAuthz(config.authz_config)
        # Monkey patching authz to non caching authz in rp_repo.
        config.nb_config.k8s_v2_client._NotebookK8sClient__rp_repo.authz = nb_authz
        config.nb_config.k8s_v2_client._NotebookK8sClient__rp_repo._ResourcePoolRepository__query_repository.authz = (
            nb_authz
        )
        kc_api: IKeycloakAPI

        default_kubeconfig = KubeConfigEnv()
        print(default_kubeconfig._kubeconfig)
        cluster_repo = ClusterRepository(session_maker=config.db.async_session_maker)
        k8s_db_cache = K8sDbCache(config.db.async_session_maker)
        client = K8sClusterClientsPool(
            lambda: get_clusters(
                kube_conf_root_dir=config.k8s_config_root,
                default_kubeconfig=default_kubeconfig,
                cluster_repo=cluster_repo,
                cache=k8s_db_cache,
                kinds_to_cache=[AMALTHEA_SESSION_GVK, JUPYTER_SESSION_GVK, BUILD_RUN_GVK, TASK_RUN_GVK],
            ),
        )

        job_client = DepositUploadJobClient(client)
        secret_client = K8sSecretClient(client)

        shipwright_client = None
        gitrepositoriesrepository_class = GitRepositoriesRepository

        if os.environ.get("CREATE_BUILDS_CLIENT", "false").lower() == "true":
            shipwright_client = ShipwrightClient(
                client=K8sClusterClientsPool(
                    lambda: get_clusters(
                        kube_conf_root_dir=config.k8s_config_root,
                        default_kubeconfig=default_kubeconfig,
                        cluster_repo=cluster_repo,
                        cache=k8s_db_cache,
                        kinds_to_cache=[AMALTHEA_SESSION_GVK, JUPYTER_SESSION_GVK, BUILD_RUN_GVK, TASK_RUN_GVK],
                    ),
                ),
                namespace=config.k8s_namespace,
            )

            gitrepositoriesrepository_class = FakeGitRepositoriesRepository

        quota_repo = QuotaRepository(K8sResourceQuotaClient(client), K8sPriorityClassClient(client))

        authenticator = DummyAuthenticator()
        gitlab_authenticator = DummyAuthenticator()
        user_always_exists = os.environ.get("DUMMY_USERSTORE_USER_ALWAYS_EXISTS", "true").lower() == "true"
        user_store = DummyUserStore(user_always_exists=user_always_exists)
        gitlab_client = DummyGitlabAPI()
        kc_api = DummyKeycloakAPI(users=[i.to_keycloak_dict() for i in dummy_users])

        authz = NonCachingAuthz(config.authz_config)
        search_updates_repo = SearchUpdatesRepo(session_maker=config.db.async_session_maker)
        oauth_client_factory = DefaultOAuthHttpClientFactory(
            config.secrets.encryption_key, config.db.async_session_maker
        )
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
            authz=authz,
        )
        rp_repo = ResourcePoolRepository(
            session_maker=config.db.async_session_maker, quotas_repo=quota_repo, authz=authz
        )
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

        git_repositories_repo = gitrepositoriesrepository_class(
            session_maker=config.db.async_session_maker,
            internal_gitlab_url=config.gitlab_url,
            enable_internal_gitlab=config.enable_internal_gitlab,
            oauth_client_factory=oauth_client_factory,
        )

        session_repo = SessionRepository(
            session_maker=config.db.async_session_maker,
            project_authz=authz,
            resource_pools=rp_repo,
            shipwright_client=shipwright_client,
            builds_config=config.builds,
            git_repositories_repo=git_repositories_repo,
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
            oauth_client_factory=oauth_client_factory,
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
        data_source_repo = DataSourceRepository(
            connected_services_repo=connected_services_repo,
            oauth_client_factory=oauth_client_factory,
            user_repo=kc_user_repo,
        )
        image_check_repo = ImageCheckRepository(
            nb_config=config.nb_config,
            connected_services_repo=connected_services_repo,
            oauth_client_factory=oauth_client_factory,
        )
        metrics_repo = MetricsRepository(session_maker=config.db.async_session_maker)
        notifications_repo = NotificationsRepository(session_maker=config.db.async_session_maker)
        git_provider_helper = GitProviderHelper(connected_services_repo, "", "", "", config.enable_internal_gitlab)
        capacity_reservation_repo = CapacityReservationRepository(
            session_maker=config.db.async_session_maker, cluster_repo=cluster_repo
        )
        occurrence_repo = OccurrenceRepository(session_maker=config.db.async_session_maker)
        resource_requests_repo = ResourceRequestsRepo(session_maker=config.db.async_session_maker)
        resource_usage_service = ResourceUsageService(resource_requests_repo)

        return cls(
            config=config,
            k8s_client=client,
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
            data_source_repo=data_source_repo,
            image_check_repo=image_check_repo,
            metrics_repo=metrics_repo,
            metrics=metrics_mock,
            shipwright_client=shipwright_client,
            authz=authz,
            low_level_user_secrets_repo=low_level_user_secrets_repo,
            url_redirect_repo=url_redirect_repo,
            git_provider_helper=git_provider_helper,
            notifications_repo=notifications_repo,
            oauth_http_client_factory=oauth_client_factory,
            capacity_reservation_repo=capacity_reservation_repo,
            occurrence_repo=occurrence_repo,
            resource_requests_repo=resource_requests_repo,
            resource_usage_service=resource_usage_service,
            zenodo_client=ZenodoAPIClient(),
            job_client=job_client,
            secret_client=secret_client,
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


def setup_shipwright(cluster: KindCluster) -> None:
    """Setup shipwright and dependencies"""

    shipwright_version = "v0.19.2"

    root = Path(__file__).parents[1]

    k8s_config.load_kube_config_from_dict(yaml.safe_load(cluster.config_yaml()))

    core_api = k8s_client.CoreV1Api()

    cmds = [
        [
            "curl",
            "--silent",
            "--location",
            f"https://raw.githubusercontent.com/shipwright-io/build/{shipwright_version}/hack/install-tekton.sh",
            "-O",
        ],
        ["bash", "install-tekton.sh"],
        [
            "kubectl",
            "apply",
            "--filename",
            f"https://github.com/shipwright-io/build/releases/download/{shipwright_version}/release.yaml",
            "--server-side",
        ],
        [
            "kubectl",
            "apply",
            "--filename",
            f"https://github.com/shipwright-io/build/releases/download/{shipwright_version}/sample-strategies.yaml",
            "--server-side",
        ],
        [
            "curl",
            "--silent",
            "--location",
            f"https://raw.githubusercontent.com/shipwright-io/build/{shipwright_version}/hack/setup-webhook-cert.sh",
            "-O",
        ],
        ["bash", "setup-webhook-cert.sh"],
        [
            "curl",
            "--silent",
            "--location",
            "https://raw.githubusercontent.com/shipwright-io/build/main/hack/storage-version-migration.sh",
            "-O",
        ],
        ["bash", "storage-version-migration.sh"],
        [
            "kubectl",
            "apply",
            "--filename",
            str(root / "components/renku_pack_builder/manifests/buildstrategy.yaml"),
            "--server-side",
        ],
    ]

    # Setup tekton and shipwright
    for cmd in cmds[0:-1]:
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=cluster.env, check=True)

    watcher = watch.Watch()

    for event in watcher.stream(
        core_api.list_namespaced_pod,
        label_selector="name=shipwright-build",
        namespace="shipwright-build",
        timeout_seconds=3 * 60,
    ):
        if event["object"].status.phase == "Running":
            watcher.stop()
            break
    else:
        raise AssertionError("Timeout waiting on shipwright to run") from None

    for event in watcher.stream(
        core_api.list_namespaced_pod,
        label_selector="name=shp-build-webhook",
        namespace="shipwright-build",
        timeout_seconds=3 * 60,
    ):
        if event["object"].status.phase == "Running":
            watcher.stop()
            break
    else:
        raise AssertionError("Timeout waiting on shp-build-webhook to run") from None

    # Add our build strategy
    subprocess.run(cmds[-1], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=cluster.env, check=True)

    # Create a dummy secret to push to registry (we wont in the tests, it's for the BuildRun registration)
    docker_config = {
        "auths": {
            "https://registry.localhost/": {
                "username": "test",
                "password": "test",
                "auth": base64.b64encode(b"test:test").decode(),
            }
        }
    }
    secret_data = {".dockerconfigjson": base64.b64encode(json.dumps(docker_config).encode()).decode()}
    secret = k8s_client.V1Secret(metadata=V1ObjectMeta(name="renku-build-secret"), data=secret_data)
    core_api.create_namespaced_secret(namespace="default", body=secret)
    secret = k8s_client.V1Secret(metadata=V1ObjectMeta(name="renku-build-private-secret"), data=secret_data)
    core_api.create_namespaced_secret(namespace="default", body=secret)


class KindCluster(AbstractContextManager):
    """Context manager that will create and tear down a k3s cluster"""

    def __init__(
        self,
        cluster_name: str,
        kubeconfig=".kind-kubeconfig.yaml",
        extra_images: list[str] | None = None,
        create_cluster: bool = True,
        setup_shipwright: bool = False,
    ):
        self.cluster_name = cluster_name
        if extra_images is None:
            extra_images = []
        self.extra_images = extra_images
        self.kubeconfig = kubeconfig
        self.env = os.environ.copy()
        self.env["KUBECONFIG"] = self.kubeconfig
        self.create_cluster = create_cluster
        self.setup_shipwright = setup_shipwright

    def __enter__(self):
        """create kind cluster"""

        if not self.create_cluster:
            return self

        create_cluster = [
            "kind",
            "create",
            "cluster",
            "--name",
            self.cluster_name,
            "--kubeconfig",
            self.kubeconfig,
        ]

        try:
            subprocess.run(create_cluster, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=self.env, check=True)
        except subprocess.SubprocessError as err:
            if err.output is not None:
                print(err.output.decode())
            else:
                print(err)
            raise

        if self.setup_shipwright:
            setup_shipwright(self)

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """delete kind cluster"""

        if self.create_cluster:
            self._delete_cluster()
        return False

    def _delete_cluster(self):
        """delete kind cluster"""

        delete_cluster = ["kind", "delete", "cluster", "--name", self.cluster_name, "--kubeconfig", self.kubeconfig]
        subprocess.run(delete_cluster, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=self.env, check=True)

    def config_yaml(self):
        with open(self.kubeconfig) as f:
            return f.read()
