from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Text, Union

import yaml

from ..api.schemas.config_server_options import ServerOptionsChoices, ServerOptionsDefaults


def _parse_str_as_bool(val: Union[str, bool]) -> bool:
    if type(val) is str:
        return val.lower() == "true"
    elif type(val) is bool:
        return val
    raise ValueError(f"Unsupported data type received, expected str or bool, got {type(val)}")


def _parse_value_as_int(val: Any) -> int:
    # NOTE: That int() does not understand scientific notation
    # even stuff that is "technically" an integer like 3e10, but float does understand it
    return int(float(val))


def _parse_value_as_float(val: Any) -> float:
    return float(val)


class CPUEnforcement(str, Enum):
    LAX: str = "lax"  # CPU limit equals 3x cpu request
    STRICT: str = "strict"  # CPU limit equals cpu request
    OFF: str = "off"  # no CPU limit at all


@dataclass
class _ServerOptionsConfig:
    defaults_path: Text
    ui_choices_path: Text

    def __post_init__(self):
        with open(self.defaults_path) as f:
            self.defaults: Dict[str, Union[Text, bool, int, float]] = ServerOptionsDefaults().loads(
                f.read()
            )
        with open(self.ui_choices_path) as f:
            self.ui_choices: Dict[str, Dict[str, Any]] = ServerOptionsChoices().loads(f.read())


@dataclass
class _SentryConfig:
    enabled: Union[Text, bool]
    dsn: Optional[Text] = None
    env: Optional[Text] = None
    sample_rate: Union[float, Text] = 0.2

    def __post_init__(self):
        self.enabled = _parse_str_as_bool(self.enabled)
        self.sample_rate = _parse_value_as_float(self.sample_rate)


@dataclass
class _GitConfig:
    url: Text
    registry: Text


@dataclass
class _GitProxyConfig:
    renku_client_secret: Text
    port: Union[Text, int] = 8080
    health_port: Union[Text, int] = 8081
    image: Text = "renku/git-https-proxy:latest"
    sentry: _SentryConfig = field(default_factory=lambda: _SentryConfig(enabled=False))
    renku_client_id: Text = "renku"

    def __post_init__(self):
        self.port = _parse_value_as_int(self.port)
        self.health_port = _parse_value_as_int(self.health_port)


@dataclass
class _GitRpcServerConfig:
    host: Text = "0.0.0.0"
    port: Union[Text, int] = 4000
    image: Text = "renku/git-rpc-server:latest"
    sentry: _SentryConfig = field(default_factory=lambda: _SentryConfig(enabled=False))

    def __post_init__(self):
        self.port = _parse_value_as_int(self.port)


@dataclass
class _GitCloneConfig:
    image: Text = "renku/git-clone:latest"
    sentry: _SentryConfig = field(default_factory=lambda: _SentryConfig(enabled=False))


@dataclass
class _SessionStorageConfig:
    pvs_enabled: Union[Text, bool] = True
    pvs_storage_class: Optional[Text] = None
    use_empty_dir_size_limit: Union[Text, bool] = False

    def __post_init__(self):
        self.pvs_enabled = _parse_str_as_bool(self.pvs_enabled)
        self.use_empty_dir_size_limit = _parse_str_as_bool(self.use_empty_dir_size_limit)


@dataclass
class _SessionOidcConfig:
    client_secret: Text = field(repr=False)
    token_url: Text
    auth_url: Text
    client_id: Text = "renku-jupyterserver"
    allow_unverified_email: Union[Text, bool] = False
    config_url: Text = "/auth/realms/Renku/.well-known/openid-configuration"

    def __post_init__(self):
        self.allow_unverified_email = _parse_str_as_bool(self.allow_unverified_email)


@dataclass
class _CustomCaCertsConfig:
    image: Text = "renku/certificates:0.0.2"
    path: Text = "/usr/local/share/ca-certificates"
    secrets: Text = "[]"

    def __post_init__(self):
        self.secrets = yaml.safe_load(self.secrets)


@dataclass
class _AmaltheaConfig:
    cache_url: Text
    group: Text = "amalthea.dev"
    version: Text = "v1alpha1"
    plural: Text = "jupyterservers"


@dataclass
class _SessionIngress:
    host: Text
    tls_secret: Optional[Text] = None
    annotations: Text = "{}"

    def __post_init__(self):
        if type(self.annotations) is Text:
            self.annotations = yaml.safe_load(self.annotations)


@dataclass
class _GenericCullingConfig:
    idle_seconds: Union[Text, int] = 86400
    max_age_seconds: Union[Text, int] = 0
    pending_seconds: Union[Text, int] = 0
    failed_seconds: Union[Text, int] = 0
    hibernated_seconds: Union[Text, int] = 86400

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
    anonymous: List[Text]
    registered: List[Text]


@dataclass
class _SessionSshConfig:
    enabled: Union[Text, bool] = False
    service_port: Union[Text, int] = 22
    container_port: Union[Text, int] = 2022
    host_key_secret: Optional[Text] = None
    host_key_location: Text = "/opt/ssh/ssh_host_keys"

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
    default_image: Text = "renku/singleuser:latest"
    enforce_cpu_limits: CPUEnforcement = CPUEnforcement.OFF
    termination_warning_duration_seconds: int = 12 * 60 * 60
    image_default_workdir: Text = "/home/jovyan"
    node_selector: Text = "{}"
    affinity: Text = "{}"
    tolerations: Text = "[]"
    init_containers: List[Text] = field(
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

    renku_namespace: Text
    sessions_namespace: Optional[Text] = None
    enabled: Union[Text, bool] = True

    def __post_init__(self):
        self.enabled = _parse_str_as_bool(self.enabled)


@dataclass
class _DynamicConfig:
    server_options: _ServerOptionsConfig
    sessions: _SessionConfig
    amalthea: _AmaltheaConfig
    sentry: _SentryConfig
    git: _GitConfig
    anonymous_sessions_enabled: Union[Text, bool] = False
    ssh_enabled: Union[Text, bool] = False
    service_prefix: str = "/notebooks"
    version: str = "0.0.0"

    def __post_init__(self):
        self.anonymous_sessions_enabled = _parse_str_as_bool(self.anonymous_sessions_enabled)
        self.ssh_enabled = _parse_str_as_bool(self.ssh_enabled)


@dataclass
class _CloudStorage:
    enabled: Union[Text, bool] = False
    storage_class: Text = "csi-rclone"
    mount_folder: Text = "/cloudstorage"
