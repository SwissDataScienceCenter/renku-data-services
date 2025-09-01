"""Base notebooks svc configuration."""

import os
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol, Self

import kr8s

from renku_data_services.base_models import APIUser
from renku_data_services.crc.db import ClusterRepository, ResourcePoolRepository
from renku_data_services.crc.models import ResourceClass
from renku_data_services.db_config.config import DBConfig
from renku_data_services.k8s.clients import (
    DummyCoreClient,
    DummySchedulingClient,
    K8sClusterClientsPool,
    K8sCoreClient,
    K8sSchedulingClient,
    K8sSecretClient,
)
from renku_data_services.k8s.config import KubeConfigEnv, get_clusters
from renku_data_services.k8s.db import K8sDbCache, QuotaRepository
from renku_data_services.notebooks.api.classes.data_service import (
    CRCValidator,
    DummyCRCValidator,
    DummyGitProviderHelper,
    GitProviderHelper,
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


@dataclass
class NotebooksConfig:
    """The notebooks' configuration."""

    server_options: ServerOptionsConfig
    sessions: _SessionConfig
    sentry: _SentryConfig
    git: _GitConfig
    k8s: _K8sConfig
    k8s_db_cache: K8sDbCache
    _kr8s_api: kr8s.asyncio.Api
    cloud_storage: _CloudStorage
    user_secrets: _UserSecrets
    crc_validator: CRCValidatorProto
    git_provider_helper: GitProviderHelperProto
    k8s_client: NotebookK8sClient[JupyterServerV1Alpha1]
    k8s_v2_client: NotebookK8sClient[AmaltheaSessionV1Alpha1]
    cluster_rp: ClusterRepository
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

    @classmethod
    def from_env(cls, db_config: DBConfig) -> Self:
        """Create a configuration object from environment variables."""
        dummy_stores = _parse_str_as_bool(os.environ.get("DUMMY_STORES", False))
        sessions_config: _SessionConfig
        git_config: _GitConfig
        kr8s_api: kr8s.asyncio.Api
        data_service_url = os.environ.get("NB_DATA_SERVICE_URL", "http://127.0.0.1:8000")
        server_options = ServerOptionsConfig.from_env()
        crc_validator: CRCValidatorProto
        git_provider_helper: GitProviderHelperProto
        k8s_namespace = os.environ.get("K8S_NAMESPACE", "default")
        kube_config_root = os.environ.get("K8S_CONFIGS_ROOT", "/secrets/kube_configs")
        v1_sessions_enabled = _parse_str_as_bool(os.environ.get("V1_SESSIONS_ENABLED", False))

        if dummy_stores:
            quota_repo = QuotaRepository(DummyCoreClient({}, {}), DummySchedulingClient({}), namespace=k8s_namespace)
            rp_repo = ResourcePoolRepository(db_config.async_session_maker, quota_repo)
            crc_validator = DummyCRCValidator()
            sessions_config = _SessionConfig._for_testing()
            git_provider_helper = DummyGitProviderHelper()
            git_config = _GitConfig("http://not.specified", "registry.not.specified")
            kr8s_api = Kr8sApiStack()  # type: ignore[assignment]
        else:
            quota_repo = QuotaRepository(K8sCoreClient(), K8sSchedulingClient(), namespace=k8s_namespace)
            rp_repo = ResourcePoolRepository(db_config.async_session_maker, quota_repo)
            crc_validator = CRCValidator(rp_repo)
            sessions_config = _SessionConfig.from_env()
            git_config = _GitConfig.from_env()
            git_provider_helper = GitProviderHelper(
                data_service_url, f"http://{sessions_config.ingress.host}", git_config.url
            )
            # NOTE: we need to get an async client as a sync client can't be used in an async way
            # But all the config code is not async, so we need to drop into the running loop, if there is one
            kr8s_api = KubeConfigEnv().api()

        k8s_config = _K8sConfig.from_env()
        k8s_db_cache = K8sDbCache(db_config.async_session_maker)
        cluster_rp = ClusterRepository(db_config.async_session_maker)

        client = K8sClusterClientsPool(
            get_clusters(
                kube_conf_root_dir=kube_config_root,
                default_cluster_namespace=k8s_config.renku_namespace,
                default_cluster_api=kr8s_api,
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
            git_provider_helper=git_provider_helper,
            k8s_client=k8s_client,
            k8s_v2_client=k8s_v2_client,
            k8s_db_cache=k8s_db_cache,
            cluster_rp=cluster_rp,
            _kr8s_api=kr8s_api,
            v1_sessions_enabled=v1_sessions_enabled,
        )
