"""Dynamic configuration."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, Union

import yaml

from ..api.schemas.config_server_options import ServerOptionsChoices, ServerOptionsDefaults


def _parse_str_as_bool(val: Union[str, bool]) -> bool:
    if isinstance(val, str):
        return val.lower() == "true"
    elif isinstance(val, bool):
        return val
    raise ValueError(f"Unsupported data type received, expected str or bool, got {type(val)}")


def _parse_value_as_int(val: Any) -> int:
    # NOTE: That int() does not understand scientific notation
    # even stuff that is "technically" an integer like 3e10, but float does understand it
    return int(float(val))


def _parse_value_as_float(val: Any) -> float:
    return float(val)


class CPUEnforcement(str, Enum):
    """CPU enforcement policies."""

    LAX: str = "lax"  # CPU limit equals 3x cpu request
    STRICT: str = "strict"  # CPU limit equals cpu request
    OFF: str = "off"  # no CPU limit at all


@dataclass
class _ServerOptionsConfig:
    defaults_path: str
    ui_choices_path: str

    def __post_init__(self):
        with open(self.defaults_path) as f:
            self.defaults: dict[str, Union[str, bool, int, float]] = ServerOptionsDefaults().loads(f.read())
        with open(self.ui_choices_path) as f:
            self.ui_choices: dict[str, dict[str, Any]] = ServerOptionsChoices().loads(f.read())


@dataclass
class _SentryConfig:
    enabled: Union[str, bool]
    dsn: Optional[str] = None
    env: Optional[str] = None
    sample_rate: Union[float, str] = 0.2

    def __post_init__(self):
        self.enabled = _parse_str_as_bool(self.enabled)
        self.sample_rate = _parse_value_as_float(self.sample_rate)


@dataclass
class _GitConfig:
    url: str
    registry: str


@dataclass
class _GitProxyConfig:
    renku_client_secret: str
    port: Union[str, int] = 8080
    health_port: Union[str, int] = 8081
    image: str = "renku/git-https-proxy:latest"
    sentry: _SentryConfig = field(default_factory=lambda: _SentryConfig(enabled=False))
    renku_client_id: str = "renku"

    def __post_init__(self):
        self.port = _parse_value_as_int(self.port)
        self.health_port = _parse_value_as_int(self.health_port)


@dataclass
class _GitRpcServerConfig:
    host: str = "0.0.0.0"
    port: Union[str, int] = 4000
    image: str = "renku/git-rpc-server:latest"
    sentry: _SentryConfig = field(default_factory=lambda: _SentryConfig(enabled=False))

    def __post_init__(self):
        self.port = _parse_value_as_int(self.port)


@dataclass
class _GitCloneConfig:
    image: str = "renku/git-clone:latest"
    sentry: _SentryConfig = field(default_factory=lambda: _SentryConfig(enabled=False))


@dataclass
class _SessionStorageConfig:
    pvs_enabled: Union[str, bool] = True
    pvs_storage_class: Optional[str] = None
    use_empty_dir_size_limit: Union[str, bool] = False

    def __post_init__(self):
        self.pvs_enabled = _parse_str_as_bool(self.pvs_enabled)
        self.use_empty_dir_size_limit = _parse_str_as_bool(self.use_empty_dir_size_limit)


@dataclass
class _SessionOidcConfig:
    client_secret: str = field(repr=False)
    token_url: str
    auth_url: str
    client_id: str = "renku-jupyterserver"
    allow_unverified_email: Union[str, bool] = False
    config_url: str = "/auth/realms/Renku/.well-known/openid-configuration"

    def __post_init__(self):
        self.allow_unverified_email = _parse_str_as_bool(self.allow_unverified_email)


@dataclass
class _CustomCaCertsConfig:
    image: str = "renku/certificates:0.0.2"
    path: str = "/usr/local/share/ca-certificates"
    secrets: str = "[]"

    def __post_init__(self):
        self.secrets = yaml.safe_load(self.secrets)


@dataclass
class _AmaltheaConfig:
    cache_url: str
    group: str = "amalthea.dev"
    version: str = "v1alpha1"
    plural: str = "jupyterservers"


@dataclass
class _SessionIngress:
    host: str
    tls_secret: Optional[str] = None
    annotations: str = "{}"

    def __post_init__(self):
        if isinstance(self.annotations, str):
            self.annotations = yaml.safe_load(self.annotations)


@dataclass
class _GenericCullingConfig:
    idle_seconds: Union[str, int] = 86400
    max_age_seconds: Union[str, int] = 0
    pending_seconds: Union[str, int] = 0
    failed_seconds: Union[str, int] = 0
    hibernated_seconds: Union[str, int] = 86400

    def __post_init__(self):
        self.idle_seconds = _parse_value_as_int(self.idle_seconds)
        self.max_age_seconds = _parse_value_as_int(self.max_age_seconds)
        self.pending_seconds = _parse_value_as_int(self.pending_seconds)
        self.failed_seconds = _parse_value_as_int(self.failed_seconds)
        self.hibernated_seconds = _parse_value_as_int(self.hibernated_seconds)


@dataclass
class _SessionCullingConfig:
    anonymous: _GenericCullingConfig
    registered: _GenericCullingConfig


@dataclass
class _SessionContainers:
    anonymous: list[str]
    registered: list[str]


@dataclass
class _SessionSshConfig:
    enabled: Union[str, bool] = False
    service_port: Union[str, int] = 22
    container_port: Union[str, int] = 2022
    host_key_secret: Optional[str] = None
    host_key_location: str = "/opt/ssh/ssh_host_keys"

    def __post_init__(self):
        self.enabled = _parse_str_as_bool(self.enabled)
        self.service_port = _parse_value_as_int(self.service_port)
        self.container_port = _parse_value_as_int(self.container_port)


@dataclass
class _SessionConfig:
    culling: _SessionCullingConfig
    git_proxy: _GitProxyConfig
    git_rpc_server: _GitRpcServerConfig
    git_clone: _GitCloneConfig
    ingress: _SessionIngress
    ca_certs: _CustomCaCertsConfig
    oidc: _SessionOidcConfig
    storage: _SessionStorageConfig
    containers: _SessionContainers
    ssh: _SessionSshConfig
    default_image: str = "renku/singleuser:latest"
    enforce_cpu_limits: CPUEnforcement = CPUEnforcement.OFF
    termination_warning_duration_seconds: int = 12 * 60 * 60
    image_default_workdir: str = "/home/jovyan"
    node_selector: str = "{}"
    affinity: str = "{}"
    tolerations: str = "[]"
    init_containers: list[str] = field(
        default_factory=lambda: [
            "init-certificates",
            "download-image",
            "git-clone",
        ]
    )

    def __post_init__(self):
        self.node_selector = yaml.safe_load(self.node_selector)
        self.affinity = yaml.safe_load(self.affinity)
        self.tolerations = yaml.safe_load(self.tolerations)


@dataclass
class _K8sConfig:
    """Defines the k8s client and namespace."""

    renku_namespace: str
    sessions_namespace: Optional[str] = None
    enabled: Union[str, bool] = True

    def __post_init__(self):
        self.enabled = _parse_str_as_bool(self.enabled)


@dataclass
class _DynamicConfig:
    server_options: _ServerOptionsConfig
    sessions: _SessionConfig
    amalthea: _AmaltheaConfig
    sentry: _SentryConfig
    git: _GitConfig
    anonymous_sessions_enabled: Union[str, bool] = False
    ssh_enabled: Union[str, bool] = False
    service_prefix: str = "/notebooks"
    version: str = "0.0.0"

    def __post_init__(self):
        self.anonymous_sessions_enabled = _parse_str_as_bool(self.anonymous_sessions_enabled)
        self.ssh_enabled = _parse_str_as_bool(self.ssh_enabled)


@dataclass
class _CloudStorage:
    enabled: Union[str, bool] = False
    storage_class: str = "csi-rclone"
    mount_folder: str = "/cloudstorage"


@dataclass
class _UserSecrets:
    image: str = "renku/secrets_mount:latest"
    secrets_storage_service_url: str = "http://renku-secrets-storage"

    def __post_init__(self):
        self.secrets_storage_service_url = self.secrets_storage_service_url.rstrip("/")
