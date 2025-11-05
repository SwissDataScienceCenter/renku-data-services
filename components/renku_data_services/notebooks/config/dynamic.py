"""Dynamic configuration."""

import json
import os
from dataclasses import dataclass, field
from enum import Enum
from io import StringIO
from typing import Any, ClassVar, Self, Union
from urllib.parse import urlunparse

import yaml

from renku_data_services.notebooks.api.schemas.config_server_options import ServerOptionsChoices, ServerOptionsDefaults
from renku_data_services.notebooks.crs import Affinity, Toleration

latest_version: str = "1.25.3"


def _parse_str_as_bool(val: Union[str, bool]) -> bool:
    if isinstance(val, str):
        return val.lower() == "true"
    elif isinstance(val, bool):
        return val
    else:
        raise ValueError(f"Unsupported data type received, expected str or bool, got {type(val)}")


def _parse_value_as_int(val: Any) -> int:
    # NOTE: That int() does not understand scientific notation
    # even stuff that is "technically" an integer like 3e10, but float does understand it
    return int(float(val))


def _parse_value_as_float(val: Any) -> float:
    return float(val)


class CPUEnforcement(str, Enum):
    """CPU enforcement policies."""

    LAX = "lax"  # CPU limit equals 3x cpu request
    STRICT = "strict"  # CPU limit equals cpu request
    OFF = "off"  # no CPU limit at all


@dataclass
class ServerOptionsConfig:
    """Config class for server options."""

    defaults: dict[str, str | bool | int | float] = field(init=False)
    ui_choices: dict[str, Any] = field(init=False)
    defaults_path: str = "/etc/renku-notebooks/server_options/server_defaults.json"
    ui_choices_path: str = "/etc/renku-notebooks/server_options/server_options.json"

    def __post_init__(self) -> None:
        with open(self.defaults_path) as f:
            self.defaults = ServerOptionsDefaults().loads(f.read())
        with open(self.ui_choices_path) as f:
            self.ui_choices = ServerOptionsChoices().loads(f.read())

    @property
    def lfs_auto_fetch_default(self) -> bool:
        """Whether lfs autofetch is enabled or not."""
        return str(self.defaults.get("lfs_auto_fetch", "false")).lower() == "true"

    @property
    def default_url_default(self) -> str:
        """Default url (path) for session."""
        return str(self.defaults.get("defaultUrl", "/lab"))

    @classmethod
    def from_env(cls) -> Self:
        """Load config from environment variables."""
        return cls(
            os.environ["NB_SERVER_OPTIONS__DEFAULTS_PATH"],
            os.environ["NB_SERVER_OPTIONS__UI_CHOICES_PATH"],
        )


@dataclass
class _SentryConfig:
    enabled: bool = False
    dsn: str | None = field(repr=False, default=None)
    env: str | None = None
    sample_rate: float = 0.2

    @classmethod
    def from_env(cls, prefix: str = "") -> Self:
        return cls(
            _parse_str_as_bool(os.environ.get(f"{prefix}SENTRY__ENABLED", False)),
            os.environ.get(f"{prefix}SENTRY__DSN", None),
            os.environ.get(f"{prefix}SENTRY__ENV", None),
            _parse_value_as_float(os.environ.get(f"{prefix}SENTRY__SAMPLE_RATE", 0.2)),
        )


@dataclass
class _GitConfig:
    url: str
    registry: str

    @classmethod
    def from_env(cls, enable_internal_gitlab: bool = True) -> Self:
        if enable_internal_gitlab:
            return cls(os.environ["NB_GIT__URL"], os.environ["NB_GIT__REGISTRY"])
        return cls("", "")


@dataclass
class _GitProxyConfig:
    renku_client_secret: str = field(repr=False)
    sentry: _SentryConfig = field(default_factory=_SentryConfig.from_env)
    port: int = 65480
    health_port: int = 65481
    image: str = f"renku/git-https-proxy:{latest_version}"
    renku_client_id: str = "renku"

    @classmethod
    def from_env(cls) -> Self:
        return cls(
            renku_client_secret=os.environ["NB_SESSIONS__GIT_PROXY__RENKU_CLIENT_SECRET"],
            renku_client_id=os.environ.get("NB_SESSIONS__GIT_PROXY__RENKU_CLIENT_ID", "renku"),
            sentry=_SentryConfig.from_env(prefix="NB_SESSIONS__GIT_PROXY__"),
            port=_parse_value_as_int(os.environ.get("NB_SESSIONS__GIT_PROXY__PORT", 65480)),
            health_port=_parse_value_as_int(os.environ.get("NB_SESSIONS__GIT_PROXY__HEALTH_PORT", 65481)),
            image=os.environ.get("NB_SESSIONS__GIT_PROXY__IMAGE", f"renku/git-https-proxy:{latest_version}"),
        )


@dataclass
class _GitRpcServerConfig:
    sentry: _SentryConfig = field(default_factory=_SentryConfig.from_env)
    host: str = "0.0.0.0"  # nosec B104
    port: int = 4000
    image: str = f"renku/git-rpc-server:{latest_version}"

    def __post_init__(self) -> None:
        self.port = _parse_value_as_int(self.port)

    @classmethod
    def from_env(cls) -> Self:
        return cls(
            image=os.environ.get("NB_SESSIONS__GIT_RPC_SERVER__IMAGE", f"renku/git-rpc-server:{latest_version}"),
            host=os.environ.get("NB_SESSIONS__GIT_RPC_SERVER__HOST", "0.0.0.0"),  # nosec B104
            port=_parse_value_as_int(os.environ.get("NB_SESSIONS__GIT_RPC_SERVER__PORT", 4000)),
            sentry=_SentryConfig.from_env(prefix="NB_SESSIONS__GIT_RPC_SERVER__"),
        )


@dataclass
class _GitCloneConfig:
    image: str = f"renku/git-clone:{latest_version}"
    sentry: _SentryConfig = field(default_factory=lambda: _SentryConfig(enabled=False))

    @classmethod
    def from_env(cls) -> Self:
        return cls(
            image=os.environ.get("NB_SESSIONS__GIT_CLONE__IMAGE", f"renku/git-clone:{latest_version}"),
            sentry=_SentryConfig.from_env(prefix="NB_SESSIONS__GIT_CLONE__"),
        )


@dataclass
class _SessionStorageConfig:
    pvs_enabled: bool = True
    pvs_storage_class: str | None = None
    use_empty_dir_size_limit: bool = False

    @classmethod
    def from_env(cls) -> Self:
        return cls(
            pvs_enabled=_parse_str_as_bool(os.environ.get("NB_SESSIONS__STORAGE__PVS_ENABLED", True)),
            pvs_storage_class=os.environ.get("NB_SESSIONS__STORAGE__PVS_STORAGE_CLASS"),
            use_empty_dir_size_limit=_parse_str_as_bool(
                os.environ.get("NB_SESSIONS__STORAGE__USE_EMPTY_DIR_SIZE_LIMIT", False)
            ),
        )


@dataclass
class _SessionOidcConfig:
    client_secret: str = field(repr=False)
    token_url: str
    auth_url: str
    issuer_url: str
    client_id: str = "renku-jupyterserver"
    allow_unverified_email: Union[str, bool] = False

    def __post_init__(self) -> None:
        self.allow_unverified_email = _parse_str_as_bool(self.allow_unverified_email)

    @classmethod
    def from_env(cls) -> Self:
        return cls(
            token_url=os.environ["NB_SESSIONS__OIDC__TOKEN_URL"],
            auth_url=os.environ["NB_SESSIONS__OIDC__AUTH_URL"],
            client_secret=os.environ["NB_SESSIONS__OIDC__CLIENT_SECRET"],
            allow_unverified_email=_parse_str_as_bool(
                os.environ.get("NB_SESSIONS__OIDC__ALLOW_UNVERIFIED_EMAIL", False)
            ),
            client_id=os.environ.get("NB_SESSIONS__OIDC__CLIENT_ID", "renku-jupyterserver"),
            issuer_url=os.environ["NB_SESSIONS__OIDC__ISSUER_URL"],
        )


@dataclass
class _CustomCaCertsConfig:
    image: str = "renku/certificates:0.0.2"
    path: str = "/usr/local/share/ca-certificates"
    secrets: list[dict[str, str]] = field(default_factory=list)

    @classmethod
    def from_env(cls) -> Self:
        return cls(
            image=os.environ.get("NB_SESSIONS__CA_CERTS__IMAGE", "renku/certificates:0.0.2"),
            path=os.environ.get("NB_SESSIONS__CA_CERTS__PATH", "/usr/local/share/ca-certificates"),
            secrets=yaml.safe_load(StringIO(os.environ.get("NB_SESSIONS__CA_CERTS__SECRETS", "[]"))),
        )


@dataclass
class _AmaltheaConfig:
    cache_url: str
    group: str = "amalthea.dev"
    version: str = "v1alpha1"
    plural: str = "jupyterservers"

    @classmethod
    def from_env(cls) -> Self:
        return cls(
            cache_url=os.environ["NB_AMALTHEA__CACHE_URL"],
            group=os.environ.get("NB_AMALTHEA__GROUP", "amalthea.dev"),
            version=os.environ.get("NB_AMALTHEA__VERSION", "v1alpha1"),
            plural=os.environ.get("NB_AMALTHEA__PLURAL", "jupyterservers"),
        )


@dataclass
class _AmaltheaV2Config:
    cache_url: str
    group: str = "amalthea.dev"
    version: str = "v1alpha1"
    plural: str = "amaltheasessions"

    @classmethod
    def from_env(cls) -> Self:
        return cls(
            cache_url=os.environ["NB_AMALTHEA_V2__CACHE_URL"],
            group=os.environ.get("NB_AMALTHEA_V2__GROUP", "amalthea.dev"),
            version=os.environ.get("NB_AMALTHEA_V2__VERSION", "v1alpha1"),
            plural=os.environ.get("NB_AMALTHEA_V2__PLURAL", "amaltheasessions"),
        )


@dataclass
class _SessionIngress:
    host: str
    tls_secret: str | None = None
    class_name: str | None = None
    annotations: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> Self:
        return cls(
            host=os.environ["NB_SESSIONS__INGRESS__HOST"],
            tls_secret=os.environ["NB_SESSIONS__INGRESS__TLS_SECRET"],
            class_name=os.environ.get("NB_SESSIONS__INGRESS__CLASS_NAME", None),
            annotations=yaml.safe_load(StringIO(os.environ.get("NB_SESSIONS__INGRESS__ANNOTATIONS", "{}"))),
        )

    @staticmethod
    def base_path(server_name: str) -> str:
        return f"/sessions/{server_name}"

    def base_url(self, server_name: str, force_https: bool = False) -> str:
        scheme = "https" if self.tls_secret else "http"
        if force_https:
            scheme = "https"
        return str(urlunparse((scheme, self.host, self.base_path(server_name), None, None, None)))


@dataclass
class _GenericCullingConfig:
    idle_seconds: int = 86400
    max_age_seconds: int = 0
    pending_seconds: int = 0
    failed_seconds: int = 0
    hibernated_seconds: int = 86400

    def __post_init__(self) -> None:
        self.idle_seconds = _parse_value_as_int(self.idle_seconds)
        self.max_age_seconds = _parse_value_as_int(self.max_age_seconds)
        self.pending_seconds = _parse_value_as_int(self.pending_seconds)
        self.failed_seconds = _parse_value_as_int(self.failed_seconds)
        self.hibernated_seconds = _parse_value_as_int(self.hibernated_seconds)

    @classmethod
    def from_env(cls, prefix: str = "") -> Self:
        return cls(
            idle_seconds=_parse_value_as_int(os.environ.get(f"{prefix}IDLE_SECONDS", 86400)),
            max_age_seconds=_parse_value_as_int(os.environ.get(f"{prefix}MAX_AGE_SECONDS", 0)),
            pending_seconds=_parse_value_as_int(os.environ.get(f"{prefix}PENDING_SECONDS", 0)),
            failed_seconds=_parse_value_as_int(os.environ.get(f"{prefix}FAILED_SECONDS", 0)),
            hibernated_seconds=_parse_value_as_int(os.environ.get(f"{prefix}HIBERNATED_SECONDS", 86400)),
        )


@dataclass
class _SessionCullingConfig:
    anonymous: _GenericCullingConfig
    registered: _GenericCullingConfig

    def __post_init__(self) -> None:
        # NOTE: We don't allow hibernating anonymous users' sessions. However, when these sessions are
        # culled, they are hibernated automatically by Amalthea. To delete them as quickly as possible
        # after hibernation, we set the threshold to the minimum possible value. Since zero means don't
        # delete, 1 is the minimum threshold value.
        self.anonymous.hibernated_seconds = 1

    @classmethod
    def from_env(cls) -> Self:
        return cls(
            anonymous=_GenericCullingConfig.from_env("NB_SESSIONS__CULLING__ANONYMOUS__"),
            registered=_GenericCullingConfig.from_env("NB_SESSIONS__CULLING__REGISTERED__"),
        )


@dataclass
class _SessionContainers:
    anonymous: list[str] = field(default_factory=list)
    registered: list[str] = field(default_factory=list)
    anonymous_default: ClassVar[list[str]] = [
        "jupyter-server",
        "passthrough-proxy",
        "git-proxy",
    ]
    registered_default: ClassVar[list[str]] = [
        "jupyter-server",
        "oauth2-proxy",
        "git-proxy",
        "git-sidecar",
    ]

    def __post_init__(self) -> None:
        if not self.anonymous:
            self.anonymous = self.anonymous_default
        if not self.registered:
            self.registered = self.registered_default

    @classmethod
    def from_env(cls) -> Self:
        return cls(
            anonymous=json.loads(
                os.environ.get("NB_SESSIONS__ANONYMOUS_CONTAINERS", json.dumps(cls.anonymous_default))
            ),
            registered=json.loads(
                os.environ.get("NB_SESSIONS__REGISTERED_CONTAINERS", json.dumps(cls.registered_default))
            ),
        )


@dataclass
class _SessionSshConfig:
    enabled: bool = False
    service_port: int = 22
    container_port: int = 2022
    host_key_secret: str | None = None
    host_key_location: str = "/opt/ssh/ssh_host_keys"

    @classmethod
    def from_env(cls) -> Self:
        return cls(
            enabled=_parse_str_as_bool(os.environ.get("NB_SESSIONS__SSH__ENABLED", False)),
            service_port=_parse_value_as_int(os.environ.get("NB_SESSIONS__SSH__SERVICE_PORT", 22)),
            container_port=_parse_value_as_int(os.environ.get("NB_SESSIONS__SSH__CONTAINER_PORT", 2022)),
            host_key_secret=os.environ.get("NB_SESSIONS__SSH__HOST_KEY_SECRET"),
            host_key_location=os.environ.get("NB_SESSIONS__SSH__HOST_KEY_LOCATION", "/opt/ssh/ssh_host_keys"),
        )


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
    node_selector: dict[str, str] = field(default_factory=dict)
    affinity: dict[str, Any] | None = None
    tolerations: list[dict[str, str]] = field(default_factory=list)
    init_containers: list[str] = field(
        default_factory=lambda: [
            "init-certificates",
            "download-image",
            "git-clone",
        ]
    )

    @classmethod
    def from_env(cls) -> Self:
        affinity = (
            yaml.safe_load(StringIO(os.environ["NB_SESSIONS__AFFINITY"]))
            if os.environ.get("NB_SESSIONS__AFFINITY") is not None
            else None
        )
        return cls(
            culling=_SessionCullingConfig.from_env(),
            git_proxy=_GitProxyConfig.from_env(),
            git_rpc_server=_GitRpcServerConfig.from_env(),
            git_clone=_GitCloneConfig.from_env(),
            ingress=_SessionIngress.from_env(),
            ca_certs=_CustomCaCertsConfig.from_env(),
            oidc=_SessionOidcConfig.from_env(),
            storage=_SessionStorageConfig.from_env(),
            containers=_SessionContainers.from_env(),
            ssh=_SessionSshConfig.from_env(),
            default_image=os.environ.get("NB_SESSIONS__DEFAULT_IMAGE", "renku/singleuser:latest"),
            enforce_cpu_limits=CPUEnforcement(os.environ.get("NB_SESSIONS__ENFORCE_CPU_LIMITS", "off")),
            termination_warning_duration_seconds=_parse_value_as_int(os.environ.get("", 12 * 60 * 60)),
            image_default_workdir="/home/jovyan",
            node_selector=yaml.safe_load(StringIO(os.environ.get("NB_SESSIONS__NODE_SELECTOR", "{}"))),
            affinity=affinity,
            tolerations=yaml.safe_load(StringIO(os.environ.get("NB_SESSIONS__TOLERATIONS", "[]"))),
        )

    @classmethod
    def _for_testing(cls) -> Self:
        return cls(
            culling=_SessionCullingConfig.from_env(),
            git_proxy=_GitProxyConfig(renku_client_secret="not-defined"),  # nosec B106
            git_rpc_server=_GitRpcServerConfig.from_env(),
            git_clone=_GitCloneConfig.from_env(),
            ingress=_SessionIngress(host="localhost", tls_secret="some-secret"),  # nosec: B106
            ca_certs=_CustomCaCertsConfig.from_env(),
            oidc=_SessionOidcConfig(
                client_id="not-defined",
                client_secret="not-defined",  # nosec B106
                token_url="http://not.defined",
                auth_url="http://not.defined",
                issuer_url="http://not.defined",
            ),
            storage=_SessionStorageConfig.from_env(),
            containers=_SessionContainers.from_env(),
            ssh=_SessionSshConfig.from_env(),
            default_image=os.environ.get("", "renku/singleuser:latest"),
            enforce_cpu_limits=CPUEnforcement(os.environ.get("", "off")),
            termination_warning_duration_seconds=_parse_value_as_int(os.environ.get("", 12 * 60 * 60)),
            image_default_workdir="/home/jovyan",
            node_selector=yaml.safe_load(StringIO(os.environ.get("", "{}"))),
            affinity=yaml.safe_load(StringIO(os.environ.get("", "{}"))),
            tolerations=yaml.safe_load(StringIO(os.environ.get("", "[]"))),
        )

    @property
    def affinity_model(self) -> Affinity | None:
        return Affinity.model_validate(self.affinity) if self.affinity is not None else None

    @property
    def tolerations_model(self) -> list[Toleration]:
        return [Toleration.model_validate(tol) for tol in self.tolerations]


@dataclass
class _K8sConfig:
    """Defines the k8s client and namespace."""

    renku_namespace: str = "default"

    @classmethod
    def from_env(cls) -> Self:
        return cls(renku_namespace=os.environ.get("KUBERNETES_NAMESPACE", "default"))


@dataclass
class _DynamicConfig:
    server_options: ServerOptionsConfig
    sessions: _SessionConfig
    amalthea: _AmaltheaConfig
    sentry: _SentryConfig
    git: _GitConfig
    anonymous_sessions_enabled: bool = False
    ssh_enabled: bool = False
    service_prefix: str = "/notebooks"
    version: str = "0.0.0"

    @classmethod
    def from_env(cls) -> Self:
        return cls(
            server_options=ServerOptionsConfig.from_env(),
            sessions=_SessionConfig.from_env(),
            amalthea=_AmaltheaConfig.from_env(),
            sentry=_SentryConfig.from_env("NB_SENTRY_"),
            git=_GitConfig.from_env(),
            anonymous_sessions_enabled=_parse_str_as_bool(os.environ.get("NB_ANONYMOUS_SESSIONS_ENABLED", False)),
            ssh_enabled=_parse_str_as_bool(os.environ.get("NB_SESSIONS__SSH__ENABLED", False)),
            service_prefix=os.environ.get("NB_SERVICE_PREFIX", "/notebooks"),
            version=os.environ.get("NB_VERSION", "0.0.0"),
        )


@dataclass
class _CloudStorage:
    enabled: Union[str, bool] = False
    storage_class: str = "csi-rclone"
    mount_folder: str = "/cloudstorage"

    @classmethod
    def from_env(cls) -> Self:
        return cls(
            enabled=_parse_str_as_bool(os.environ.get("NB_CLOUD_STORAGE__ENABLED", False)),
            storage_class=os.environ.get("NB_CLOUD_STORAGE__STORAGE_CLASS", "csi-rclone"),
            mount_folder=os.environ.get("NB_CLOUD_STORAGE__MOUNT_FOLDER", "/cloudstorage"),
        )


@dataclass
class _UserSecrets:
    image: str = f"renku/secrets_mount:{latest_version}"
    secrets_storage_service_url: str = "http://renku-secrets-storage"

    def __post_init__(self) -> None:
        self.secrets_storage_service_url = self.secrets_storage_service_url.rstrip("/")

    @classmethod
    def from_env(cls) -> Self:
        return cls(
            image=os.environ.get("NB_USER_SECRETS__IMAGE", f"renku/secrets_mount:{latest_version}"),
            secrets_storage_service_url=os.environ.get(
                "NB_USER_SECRETS__SECRETS_STORAGE_SERVICE_URL", "http://renku-secrets-storage"
            ),
        )
