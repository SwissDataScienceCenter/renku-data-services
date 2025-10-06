"""Base notebooks svc configuration."""

import os
from collections.abc import Awaitable
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol, Self

import kr8s

from renku_data_services.base_models import APIUser
from renku_data_services.crc.db import ClusterRepository, ResourcePoolRepository
from renku_data_services.crc.models import ClusterSettings, ResourceClass, SessionProtocol
from renku_data_services.db_config.config import DBConfig
from renku_data_services.errors import errors
from renku_data_services.k8s.clients import (
    DummyCoreClient,
    DummySchedulingClient,
    K8sClusterClientsPool,
    K8sCoreClient,
    K8sSchedulingClient,
    K8sSecretClient,
)
from renku_data_services.k8s.config import KubeConfig, KubeConfigEnv, get_clusters
from renku_data_services.k8s.db import K8sDbCache, QuotaRepository
from renku_data_services.notebooks.api.classes.data_service import (
    CRCValidator,
    DummyCRCValidator,
)
from renku_data_services.notebooks.api.classes.k8s_client import NotebookK8sClient
from renku_data_services.notebooks.api.classes.repository import GitProvider
from renku_data_services.notebooks.api.schemas.server_options import ServerOptions
from renku_data_services.notebooks.config.dynamic import (
    ServerOptionsConfig,
    _CloudStorage,
    _GitConfig,
    _K8sConfig,
    _parse_str_as_bool,
    _SentryConfig,
    _SessionConfig,
    _UserSecrets,
)
from renku_data_services.notebooks.config.static import _ServersGetEndpointAnnotations
from renku_data_services.notebooks.constants import AMALTHEA_SESSION_GVK, JUPYTER_SESSION_GVK
from renku_data_services.notebooks.crs import AmaltheaSessionV1Alpha1, JupyterServerV1Alpha1
from renku_data_services.session.constants import BUILD_RUN_GVK, TASK_RUN_GVK


class CRCValidatorProto(Protocol):
    """Compute resource control validator."""

    async def validate_class_storage(
        self,
        user: APIUser,
        class_id: int,
        storage: Optional[int] = None,
    ) -> ServerOptions:
        """Validate the resource class storage for the session."""
        ...

    async def get_default_class(self) -> ResourceClass:
        """Get the default resource class."""
        ...

    async def find_acceptable_class(
        self, user: APIUser, requested_server_options: ServerOptions
    ) -> Optional[ServerOptions]:
        """Find a suitable resource class based on resource requirements."""
        ...


class GitProviderHelperProto(Protocol):
    """Git provider protocol."""

    async def get_providers(self, user: APIUser) -> list[GitProvider]:
        """Get a list of git providers."""
        ...


class Kr8sApiStack:
    """Class maintaining a stack of current api clients.

    Used for testing.
    """

    stack: list[kr8s.Api] = list()

    def push(self, api: kr8s.Api) -> None:
        """Push a new api client onto the stack."""
        self.stack.append(api)

    def pop(self) -> kr8s.Api:
        """Pop the current kr8s api client from the stack."""
        return self.stack.pop()

    @property
    def current(self) -> kr8s.Api:
        """Get the currently active api client."""
        return self.stack[-1]

    def __getattribute__(self, name: str) -> Any:
        """Pass on requests to current api client."""
        if name in ["push", "pop", "current", "stack"]:
            return object.__getattribute__(self, name)
        return object.__getattribute__(self.current, name)


class TestKubeConfig(KubeConfig):
    """Kubeconfig used for testing."""

    def __init__(
        self,
        kubeconfig: str | None = None,
        current_context_name: str | None = None,
        ns: str | None = None,
        sa: str | None = None,
        url: str | None = None,
    ) -> None:
        super().__init__(kubeconfig, current_context_name, ns, sa, url)
        self.__stack = Kr8sApiStack()

    def sync_api(self) -> kr8s.Api:
        """Instantiate the sync Kr8s Api object based on the configuration."""
        return self.__stack  # type: ignore[return-value]

    def api(self) -> Awaitable[kr8s.asyncio.Api]:
        """Instantiate the async Kr8s Api object based on the configuration."""

        async def _api() -> kr8s.asyncio.Api:
            return self.__stack  # type: ignore[return-value]

        return _api()


@dataclass
class NotebooksConfig:
    """The notebooks' configuration."""

    server_options: ServerOptionsConfig
    sessions: _SessionConfig
    sentry: _SentryConfig
    git: _GitConfig
    k8s: _K8sConfig
    k8s_db_cache: K8sDbCache
    cloud_storage: _CloudStorage
    user_secrets: _UserSecrets
    crc_validator: CRCValidatorProto
    k8s_client: NotebookK8sClient[JupyterServerV1Alpha1]
    k8s_v2_client: NotebookK8sClient[AmaltheaSessionV1Alpha1]
    cluster_rp: ClusterRepository
    enable_internal_gitlab: bool
    current_resource_schema_version: int = 1
    anonymous_sessions_enabled: bool = False
    ssh_enabled: bool = False
    service_prefix: str = "/notebooks"
    version: str = "0.0.0"
    keycloak_realm: str = "Renku"
    data_service_url: str = "http://renku-data-service"
    dummy_stores: bool = False
    session_get_endpoint_annotations: _ServersGetEndpointAnnotations = field(
        default_factory=_ServersGetEndpointAnnotations
    )
    session_id_cookie_name: str = "_renku_session"  # NOTE: This cookie name is set and controlled by the gateway
    v1_sessions_enabled: bool = False
    local_cluster_session_service_account: str | None = None

    @classmethod
    def from_env(cls, db_config: DBConfig, enable_internal_gitlab: bool) -> Self:
        """Create a configuration object from environment variables."""
        enable_internal_gitlab = os.getenv("ENABLE_INTERNAL_GITLAB", "false").lower() == "true"
        dummy_stores = _parse_str_as_bool(os.environ.get("DUMMY_STORES", False))
        sessions_config: _SessionConfig
        git_config: _GitConfig
        default_kubeconfig = KubeConfigEnv()
        data_service_url = os.environ.get("NB_DATA_SERVICE_URL", "http://127.0.0.1:8000")
        server_options = ServerOptionsConfig.from_env()
        crc_validator: CRCValidatorProto
        k8s_namespace = os.environ.get("K8S_NAMESPACE", "default")
        kube_config_root = os.environ.get("K8S_CONFIGS_ROOT", "/secrets/kube_configs")
        v1_sessions_enabled = _parse_str_as_bool(os.environ.get("V1_SESSIONS_ENABLED", False))

        if dummy_stores:
            quota_repo = QuotaRepository(DummyCoreClient({}, {}), DummySchedulingClient({}), namespace=k8s_namespace)
            rp_repo = ResourcePoolRepository(db_config.async_session_maker, quota_repo)
            crc_validator = DummyCRCValidator()
            sessions_config = _SessionConfig._for_testing()
            git_config = _GitConfig("http://not.specified", "registry.not.specified")

        else:
            quota_repo = QuotaRepository(K8sCoreClient(), K8sSchedulingClient(), namespace=k8s_namespace)
            rp_repo = ResourcePoolRepository(db_config.async_session_maker, quota_repo)
            crc_validator = CRCValidator(rp_repo)
            sessions_config = _SessionConfig.from_env()
            git_config = _GitConfig.from_env(enable_internal_gitlab=enable_internal_gitlab)
            git_provider_helper = GitProviderHelper(
                service_url=data_service_url,
                renku_url=f"http://{sessions_config.ingress.host}",
                internal_gitlab_url=git_config.url,
                enable_internal_gitlab=enable_internal_gitlab,
            )

        k8s_config = _K8sConfig.from_env()
        k8s_db_cache = K8sDbCache(db_config.async_session_maker)
        cluster_rp = ClusterRepository(db_config.async_session_maker)

        client = K8sClusterClientsPool(
            get_clusters(
                kube_conf_root_dir=kube_config_root,
                default_kubeconfig=default_kubeconfig,
                cluster_repo=cluster_rp,
                cache=k8s_db_cache,
                kinds_to_cache=[AMALTHEA_SESSION_GVK, JUPYTER_SESSION_GVK, BUILD_RUN_GVK, TASK_RUN_GVK],
            )
        )
        secrets_client = K8sSecretClient(client)

        k8s_client = NotebookK8sClient(
            client=client,
            secrets_client=secrets_client,
            rp_repo=rp_repo,
            session_type=JupyterServerV1Alpha1,
            gvk=JUPYTER_SESSION_GVK,
            username_label="renku.io/userId",
        )
        k8s_v2_client = NotebookK8sClient(
            client=client,
            secrets_client=secrets_client,
            rp_repo=rp_repo,
            # NOTE: v2 sessions have no userId label, the safe-username label is the keycloak user ID
            session_type=AmaltheaSessionV1Alpha1,
            gvk=AMALTHEA_SESSION_GVK,
            username_label="renku.io/safe-username",
        )

        return cls(
            server_options=server_options,
            sessions=sessions_config,
            sentry=_SentryConfig.from_env(),
            git=git_config,
            k8s=k8s_config,
            cloud_storage=_CloudStorage.from_env(),
            user_secrets=_UserSecrets.from_env(),
            current_resource_schema_version=1,
            anonymous_sessions_enabled=_parse_str_as_bool(os.environ.get("NB_ANONYMOUS_SESSIONS_ENABLED", False)),
            ssh_enabled=_parse_str_as_bool(os.environ.get("NB_SSH_ENABLED", False)),
            version=os.environ.get("NB_VERSION", "0.0.0"),
            keycloak_realm=os.environ.get("NB_KEYCLOAK_REALM", "Renku"),
            data_service_url=data_service_url,
            dummy_stores=dummy_stores,
            crc_validator=crc_validator,
            k8s_client=k8s_client,
            k8s_v2_client=k8s_v2_client,
            k8s_db_cache=k8s_db_cache,
            cluster_rp=cluster_rp,
            v1_sessions_enabled=v1_sessions_enabled,
            enable_internal_gitlab=enable_internal_gitlab,
            local_cluster_session_service_account=os.environ.get("LOCAL_CLUSTER_SESSION_SERVICE_ACCOUNT"),
        )

    def local_cluster_settings(self) -> ClusterSettings:
        """The cluster settings for the local cluster where the Renku services are installed."""
        if not self.sessions.ingress.tls_secret:
            raise errors.ProgrammingError(message="The tls secret must be defined for a local cluster.")
        return ClusterSettings(
            name="local-cluster-settings",
            config_name="",
            session_protocol=SessionProtocol.HTTPS,
            session_host=self.sessions.ingress.host,
            session_port=443,
            session_path="/sessions",
            session_ingress_annotations=self.sessions.ingress.annotations,
            session_tls_secret_name=self.sessions.ingress.tls_secret,
            session_storage_class=self.sessions.storage.pvs_storage_class,
            service_account_name=self.local_cluster_session_service_account,
        )
