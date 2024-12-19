"""Base motebooks svc configuration."""

import os
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol, Self

from renku_data_services.base_models import APIUser
from renku_data_services.crc.db import ResourcePoolRepository
from renku_data_services.crc.models import ResourceClass
from renku_data_services.db_config.config import DBConfig
from renku_data_services.k8s.clients import K8sCoreClient, K8sSchedulingClient
from renku_data_services.k8s.quota import QuotaRepository
from renku_data_services.notebooks.api.classes.data_service import (
    CloudStorageConfig,
    CRCValidator,
    DummyCRCValidator,
    DummyGitProviderHelper,
    DummyStorageValidator,
    GitProviderHelper,
    StorageValidator,
)
from renku_data_services.notebooks.api.classes.k8s_client import (
    AmaltheaSessionV1Alpha1Kr8s,
    JupyterServerV1Alpha1Kr8s,
    K8sClient,
    NamespacedK8sClient,
    ServerCache,
)
from renku_data_services.notebooks.api.classes.repository import GitProvider
from renku_data_services.notebooks.api.schemas.server_options import ServerOptions
from renku_data_services.notebooks.config.dynamic import (
    _AmaltheaConfig,
    _AmaltheaV2Config,
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


class StorageValidatorProto(Protocol):
    """Cloud storage validator protocol."""

    async def get_storage_by_id(
        self, user: APIUser, internal_gitlab_user: APIUser, endpoint: str, storage_id: str
    ) -> CloudStorageConfig:
        """Get storage by ID."""
        ...

    async def validate_storage_configuration(self, configuration: dict[str, Any], source_path: str) -> None:
        """Validate a storage configuration."""
        ...

    async def obscure_password_fields_for_storage(self, configuration: dict[str, Any]) -> dict[str, Any]:
        """Obscure passsword fields in storage credentials."""
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
    amalthea: _AmaltheaConfig
    sentry: _SentryConfig
    git: _GitConfig
    k8s: _K8sConfig
    cloud_storage: _CloudStorage
    user_secrets: _UserSecrets
    crc_validator: CRCValidatorProto
    storage_validator: StorageValidatorProto
    git_provider_helper: GitProviderHelperProto
    k8s_client: K8sClient[JupyterServerV1Alpha1, JupyterServerV1Alpha1Kr8s]
    k8s_v2_client: K8sClient[AmaltheaSessionV1Alpha1, AmaltheaSessionV1Alpha1Kr8s]
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
        storage_validator: StorageValidatorProto
        git_provider_helper: GitProviderHelperProto
        k8s_namespace = os.environ.get("K8S_NAMESPACE", "default")
        quota_repo: QuotaRepository
        if dummy_stores:
            crc_validator = DummyCRCValidator()
            sessions_config = _SessionConfig._for_testing()
            storage_validator = DummyStorageValidator()
            git_provider_helper = DummyGitProviderHelper()
            amalthea_config = _AmaltheaConfig(cache_url="http://not.specified")
            amalthea_v2_config = _AmaltheaV2Config(cache_url="http://not.specified")
            git_config = _GitConfig("http://not.specified", "registry.not.specified")
        else:
            quota_repo = QuotaRepository(K8sCoreClient(), K8sSchedulingClient(), namespace=k8s_namespace)
            rp_repo = ResourcePoolRepository(db_config.async_session_maker, quota_repo)
            crc_validator = CRCValidator(rp_repo)
            sessions_config = _SessionConfig.from_env()
            storage_validator = StorageValidator(data_service_url)
            amalthea_config = _AmaltheaConfig.from_env()
            amalthea_v2_config = _AmaltheaV2Config.from_env()
            git_config = _GitConfig.from_env()
            git_provider_helper = GitProviderHelper(
                data_service_url, f"http://{sessions_config.ingress.host}", git_config.url
            )

        k8s_config = _K8sConfig.from_env()
        renku_ns_client = NamespacedK8sClient(
            k8s_config.renku_namespace, JupyterServerV1Alpha1, JupyterServerV1Alpha1Kr8s
        )
        js_cache = ServerCache(amalthea_config.cache_url, JupyterServerV1Alpha1)
        k8s_client = K8sClient(
            cache=js_cache,
            renku_ns_client=renku_ns_client,
            username_label="renku.io/userId",
            # NOTE: if testing then we should skip the cache if unavailable because we dont deploy the cache in tests
            skip_cache_if_unavailable=dummy_stores,
        )
        v2_cache = ServerCache(amalthea_v2_config.cache_url, AmaltheaSessionV1Alpha1)
        renku_ns_v2_client = NamespacedK8sClient(
            k8s_config.renku_namespace, AmaltheaSessionV1Alpha1, AmaltheaSessionV1Alpha1Kr8s
        )
        k8s_v2_client = K8sClient(
            cache=v2_cache,
            renku_ns_client=renku_ns_v2_client,
            # NOTE: v2 sessions have no userId label, the safe-username label is the keycloak user ID
            username_label="renku.io/safe-username",
            # NOTE: if testing then we should skip the cache if unavailable because we dont deploy the cache in tests
            skip_cache_if_unavailable=dummy_stores,
        )
        return cls(
            server_options=server_options,
            sessions=sessions_config,
            amalthea=amalthea_config,
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
            storage_validator=storage_validator,
            git_provider_helper=git_provider_helper,
            k8s_client=k8s_client,
            k8s_v2_client=k8s_v2_client,
        )
