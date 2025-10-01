"""Dependency management for data api."""

from __future__ import annotations

import functools
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from authlib.integrations.httpx_client import AsyncOAuth2Client
from yaml import safe_load

import renku_data_services.base_models as base_models
import renku_data_services.connected_services
import renku_data_services.crc
import renku_data_services.data_connectors
import renku_data_services.platform
import renku_data_services.repositories
import renku_data_services.search
import renku_data_services.storage
import renku_data_services.users
from renku_data_services.authn.dummy import DummyAuthenticator, DummyUserStore
from renku_data_services.authn.gitlab import EmptyGitlabAuthenticator, GitlabAuthenticator
from renku_data_services.authn.keycloak import KcUserStore, KeycloakAuthenticator
from renku_data_services.authz.authz import Authz
from renku_data_services.connected_services.db import ConnectedServicesRepository
from renku_data_services.crc import models as crc_models
from renku_data_services.crc.db import ClusterRepository, ResourcePoolRepository, UserRepository
from renku_data_services.crc.server_options import (
    ServerOptions,
    ServerOptionsDefaults,
    generate_default_resource_pool,
)
from renku_data_services.data_api.config import Config
from renku_data_services.data_connectors.db import (
    DataConnectorRepository,
    DataConnectorSecretRepository,
)
from renku_data_services.git.gitlab import DummyGitlabAPI, EmptyGitlabAPI, GitlabAPI
from renku_data_services.k8s.clients import (
    DummyCoreClient,
    DummySchedulingClient,
    K8sClusterClientsPool,
    K8sCoreClient,
    K8sSchedulingClient,
)
from renku_data_services.k8s.config import KubeConfigEnv
from renku_data_services.k8s.db import K8sDbCache, QuotaRepository
from renku_data_services.message_queue.db import ReprovisioningRepository
from renku_data_services.metrics.core import StagingMetricsService
from renku_data_services.metrics.db import MetricsRepository
from renku_data_services.namespace.db import GroupRepository
from renku_data_services.notebooks.api.classes.data_service import GitProviderHelper2
from renku_data_services.notebooks.config import GitProviderHelperProto, get_clusters
from renku_data_services.notebooks.constants import AMALTHEA_SESSION_GVK, JUPYTER_SESSION_GVK
from renku_data_services.platform.db import PlatformRepository, UrlRedirectRepository
from renku_data_services.project.db import (
    ProjectMemberRepository,
    ProjectMigrationRepository,
    ProjectRepository,
    ProjectSessionSecretRepository,
)
from renku_data_services.repositories.db import GitRepositoriesRepository
from renku_data_services.search import query_manual
from renku_data_services.search.db import SearchUpdatesRepo
from renku_data_services.search.reprovision import SearchReprovision
from renku_data_services.secrets.db import LowLevelUserSecretsRepo, UserSecretsRepo
from renku_data_services.session.constants import BUILD_RUN_GVK, TASK_RUN_GVK
from renku_data_services.session.db import SessionRepository
from renku_data_services.session.k8s_client import ShipwrightClient
from renku_data_services.storage.db import StorageRepository
from renku_data_services.users.db import UserPreferencesRepository
from renku_data_services.users.db import UserRepo as KcUserRepo
from renku_data_services.users.dummy_kc_api import DummyKeycloakAPI
from renku_data_services.users.kc_api import IKeycloakAPI, KeycloakAPI
from renku_data_services.users.models import UnsavedUserInfo
from renku_data_services.utils.core import merge_api_specs

default_resource_pool = crc_models.ResourcePool(
    name="default",
    classes=[
        crc_models.ResourceClass(
            name="small",
            cpu=0.5,
            memory=1,
            max_storage=20,
            gpu=0,
            default=True,
        ),
        crc_models.ResourceClass(
            name="large",
            cpu=1.0,
            memory=2,
            max_storage=20,
            gpu=0,
            default=False,
        ),
    ],
    quota=None,
    public=True,
    default=True,
)


@dataclass
class DependencyManager:
    """Configuration for the Data service."""

    config: Config

    user_store: base_models.UserStore
    authenticator: base_models.Authenticator
    gitlab_authenticator: base_models.Authenticator
    quota_repo: QuotaRepository
    gitlab_client: base_models.GitlabAPIProtocol
    kc_api: IKeycloakAPI
    authz: Authz
    user_repo: UserRepository
    rp_repo: ResourcePoolRepository
    storage_repo: StorageRepository
    project_repo: ProjectRepository
    project_migration_repo: ProjectMigrationRepository
    group_repo: GroupRepository
    reprovisioning_repo: ReprovisioningRepository
    search_updates_repo: SearchUpdatesRepo
    search_reprovisioning: SearchReprovision
    session_repo: SessionRepository
    user_preferences_repo: UserPreferencesRepository
    kc_user_repo: KcUserRepo
    low_level_user_secrets_repo: LowLevelUserSecretsRepo
    user_secrets_repo: UserSecretsRepo
    project_member_repo: ProjectMemberRepository
    project_session_secret_repo: ProjectSessionSecretRepository
    connected_services_repo: ConnectedServicesRepository
    git_repositories_repo: GitRepositoriesRepository
    platform_repo: PlatformRepository
    data_connector_repo: DataConnectorRepository
    data_connector_secret_repo: DataConnectorSecretRepository
    cluster_repo: ClusterRepository
    metrics_repo: MetricsRepository
    metrics: StagingMetricsService
    shipwright_client: ShipwrightClient | None
    url_redirect_repo: UrlRedirectRepository
    git_provider_helper: GitProviderHelperProto

    spec: dict[str, Any] = field(init=False, repr=False, default_factory=dict)
    app_name: str = "renku_data_services"
    default_resource_pool_file: str | None = None
    default_resource_pool: crc_models.ResourcePool = default_resource_pool
    async_oauth2_client_class: type[AsyncOAuth2Client] = AsyncOAuth2Client

    @staticmethod
    @functools.cache
    def load_apispec() -> dict[str, Any]:
        """Load apispec with caching.

        Note: loading these files takes quite some time and is repeated for each test. Having
        them cached in this method reduces that time significantly.
        """
        files = [
            renku_data_services.crc.__file__,
            renku_data_services.storage.__file__,
            renku_data_services.users.__file__,
            renku_data_services.project.__file__,
            renku_data_services.namespace.__file__,
            renku_data_services.session.__file__,
            renku_data_services.connected_services.__file__,
            renku_data_services.repositories.__file__,
            renku_data_services.notebooks.__file__,
            renku_data_services.platform.__file__,
            renku_data_services.data_connectors.__file__,
            renku_data_services.search.__file__,
        ]

        api_specs = []

        # NOTE: Read spec files required for Swagger
        for file in files:
            spec_file = Path(file).resolve().parent / "api.spec.yaml"
            with open(spec_file) as f:
                yaml_content = safe_load(f)
                if file == renku_data_services.search.__file__:
                    qm = query_manual.safe_manual_to_str()
                    yaml_content["paths"]["/search/query"]["get"]["description"] = qm

                api_specs.append(yaml_content)

        return merge_api_specs(*api_specs)

    def __post_init__(self) -> None:
        self.spec = self.load_apispec()

        if self.default_resource_pool_file is not None:
            with open(self.default_resource_pool_file) as f:
                self.default_resource_pool = crc_models.ResourcePool.from_dict(safe_load(f))
        if (
            self.config.server_options.defaults_path is not None
            and self.config.server_options.ui_choices_path is not None
        ):
            with open(self.config.server_options.ui_choices_path) as f:
                options = ServerOptions.model_validate(safe_load(f))
            with open(self.config.server_options.defaults_path) as f:
                defaults = ServerOptionsDefaults.model_validate(safe_load(f))
            self.default_resource_pool = generate_default_resource_pool(options, defaults)

    @classmethod
    def from_env(cls) -> DependencyManager:
        """Create a config from environment variables."""

        user_store: base_models.UserStore
        authenticator: base_models.Authenticator
        gitlab_authenticator: base_models.Authenticator
        gitlab_client: base_models.GitlabAPIProtocol
        shipwright_client: ShipwrightClient | None = None

        config = Config.from_env()
        kc_api: IKeycloakAPI
        cluster_repo = ClusterRepository(session_maker=config.db.async_session_maker)

        if config.dummy_stores:
            authenticator = DummyAuthenticator()
            gitlab_authenticator = DummyAuthenticator()
            quota_repo = QuotaRepository(
                DummyCoreClient({}, {}), DummySchedulingClient({}), namespace=config.k8s_namespace
            )
            user_always_exists = os.environ.get("DUMMY_USERSTORE_USER_ALWAYS_EXISTS", "true").lower() == "true"
            user_store = DummyUserStore(user_always_exists=user_always_exists)
            gitlab_client = DummyGitlabAPI()
            dummy_users = [
                UnsavedUserInfo(id="user1", first_name="user1", last_name="doe", email="user1@doe.com"),
                UnsavedUserInfo(id="user2", first_name="user2", last_name="doe", email="user2@doe.com"),
            ]
            kc_api = DummyKeycloakAPI(users=[i.to_keycloak_dict() for i in dummy_users])
        else:
            quota_repo = QuotaRepository(K8sCoreClient(), K8sSchedulingClient(), namespace=config.k8s_namespace)
            assert config.keycloak is not None

            authenticator = KeycloakAuthenticator.new(config.keycloak)
            if config.enable_internal_gitlab:
                assert config.gitlab_url
                gitlab_authenticator = GitlabAuthenticator(gitlab_url=config.gitlab_url)
                gitlab_client = GitlabAPI(gitlab_url=config.gitlab_url)
            else:
                gitlab_authenticator = EmptyGitlabAuthenticator()
                gitlab_client = EmptyGitlabAPI()
            user_store = KcUserStore(keycloak_url=config.keycloak.url, realm=config.keycloak.realm)
            kc_api = KeycloakAPI(
                keycloak_url=config.keycloak.url,
                client_id=config.keycloak.client_id,
                client_secret=config.keycloak.client_secret,
                realm=config.keycloak.realm,
            )
            if config.builds.enabled:
                k8s_db_cache = K8sDbCache(config.db.async_session_maker)
                kr8s_api = KubeConfigEnv().api()
                shipwright_client = ShipwrightClient(
                    client=K8sClusterClientsPool(
                        get_clusters(
                            kube_conf_root_dir=config.k8s_config_root,
                            default_cluster_namespace=config.k8s_namespace,
                            default_cluster_api=kr8s_api,
                            cluster_repo=cluster_repo,
                            cache=k8s_db_cache,
                            kinds_to_cache=[AMALTHEA_SESSION_GVK, JUPYTER_SESSION_GVK, BUILD_RUN_GVK, TASK_RUN_GVK],
                        ),
                    ),
                    namespace=config.k8s_namespace,
                )

        authz = Authz(config.authz_config)
        search_updates_repo = SearchUpdatesRepo(session_maker=config.db.async_session_maker)
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
            shipwright_client=shipwright_client,
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
        git_provider_helper = GitProviderHelper2.create(connected_services_repo, config.enable_internal_gitlab)
        metrics_repo = MetricsRepository(session_maker=config.db.async_session_maker)
        metrics = StagingMetricsService(enabled=config.posthog.enabled, metrics_repo=metrics_repo)
        return cls(
            config,
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
            metrics=metrics,
            shipwright_client=shipwright_client,
            authz=authz,
            low_level_user_secrets_repo=low_level_user_secrets_repo,
            url_redirect_repo=url_redirect_repo,
            git_provider_helper=git_provider_helper,
        )
