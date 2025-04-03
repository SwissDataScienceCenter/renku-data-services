"""Base motebooks svc configuration."""

import os
from dataclasses import dataclass, field
from typing import Optional, Protocol, Self

import kr8s

from renku_data_services.base_models import APIUser
from renku_data_services.crc.db import ResourcePoolRepository
from renku_data_services.crc.models import ResourceClass
from renku_data_services.db_config.config import DBConfig
from renku_data_services.k8s.clients import K8sCoreClient, K8sSchedulingClient
from renku_data_services.k8s.quota import QuotaRepository
from renku_data_services.k8s_watcher.db import CachedK8sClient, Cluster, K8sDbCache
from renku_data_services.k8s_watcher.models import ClusterId
from renku_data_services.notebooks.api.classes.data_service import (
    CRCValidator,
    DummyCRCValidator,
    DummyGitProviderHelper,
    GitProviderHelper,
)
from renku_data_services.notebooks.api.classes.k8s_client import (
    K8sClient,
)
from renku_data_services.notebooks.api.classes.repository import GitProvider
from renku_data_services.notebooks.api.schemas.server_options import ServerOptions
from renku_data_services.notebooks.config.dynamic import (
    _CloudStorage,
    _GitConfig,
    _K8sConfig,
    _parse_str_as_bool,
    _SentryConfig,
    _ServerOptionsConfig,
    _SessionConfig,
    _UserSecrets,
)
from renku_data_services.notebooks.config.static import _ServersGetEndpointAnnotations
from renku_data_services.notebooks.crs import AmaltheaSessionV1Alpha1, JupyterServerV1Alpha1


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


@dataclass
class NotebooksConfig:
    """The notebooks configuration."""

    server_options: _ServerOptionsConfig
    sessions: _SessionConfig
    sentry: _SentryConfig
    git: _GitConfig
    k8s: _K8sConfig
    cloud_storage: _CloudStorage
    user_secrets: _UserSecrets
    crc_validator: CRCValidatorProto
    git_provider_helper: GitProviderHelperProto
    k8s_client: K8sClient[JupyterServerV1Alpha1]
    k8s_v2_client: K8sClient[AmaltheaSessionV1Alpha1]
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

    @classmethod
    def from_env(cls, db_config: DBConfig) -> Self:
        """Create a configuration object from environment variables."""
        dummy_stores = _parse_str_as_bool(os.environ.get("DUMMY_STORES", False))
        sessions_config: _SessionConfig
        git_config: _GitConfig
        data_service_url = os.environ.get("NB_DATA_SERVICE_URL", "http://127.0.0.1:8000")
        server_options = _ServerOptionsConfig.from_env()
        crc_validator: CRCValidatorProto
        git_provider_helper: GitProviderHelperProto
        k8s_namespace = os.environ.get("K8S_NAMESPACE", "default")
        quota_repo: QuotaRepository
        db = DBConfig.from_env()
        if dummy_stores:
            crc_validator = DummyCRCValidator()
            sessions_config = _SessionConfig._for_testing()
            git_provider_helper = DummyGitProviderHelper()
            git_config = _GitConfig("http://not.specified", "registry.not.specified")
        else:
            quota_repo = QuotaRepository(K8sCoreClient(), K8sSchedulingClient(), namespace=k8s_namespace)
            rp_repo = ResourcePoolRepository(db_config.async_session_maker, quota_repo)
            crc_validator = CRCValidator(rp_repo)
            sessions_config = _SessionConfig.from_env()
            git_config = _GitConfig.from_env()
            git_provider_helper = GitProviderHelper(
                data_service_url, f"http://{sessions_config.ingress.host}", git_config.url
            )

        k8s_config = _K8sConfig.from_env()
        cluster_id = ClusterId("renkulab")
        clusters = {cluster_id: Cluster(id=cluster_id, namespace=k8s_config.renku_namespace, api=kr8s.api())}
        v2_cache = CachedK8sClient(
            clusters=clusters,
            cache=K8sDbCache(db.async_session_maker),
            kinds_to_cache=[AmaltheaSessionV1Alpha1.kind, JupyterServerV1Alpha1.kind],
        )
        k8s_client = K8sClient(
            cached_client=v2_cache,
            username_label="renku.io/userId",
            namespace=k8s_config.renku_namespace,
            cluster=cluster_id,
            server_type=JupyterServerV1Alpha1,
        )
        k8s_v2_client = K8sClient(
            cached_client=v2_cache,
            # NOTE: v2 sessions have no userId label, the safe-username label is the keycloak user ID
            username_label="renku.io/safe-username",
            namespace=k8s_config.renku_namespace,
            cluster=cluster_id,
            server_type=AmaltheaSessionV1Alpha1,
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
        )
