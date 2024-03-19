import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, Optional, Protocol, Text, Union

import dataconf

from ..api.classes.k8s_client import JsServerCache, K8sClient, NamespacedK8sClient
from .dynamic import (
    _AmaltheaConfig,
    _CloudStorage,
    _GitConfig,
    _K8sConfig,
    _parse_str_as_bool,
    _SentryConfig,
    _ServerOptionsConfig,
    _SessionConfig,
)
from .static import _ServersGetEndpointAnnotations

if TYPE_CHECKING:
    from ..api.classes.data_service import CloudStorageConfig
    from ..api.classes.user import User
    from ..api.schemas.server_options import ServerOptions


class CRCValidatorProto(Protocol):
    def validate_class_storage(
        self,
        user: "User",
        class_id: int,
        storage: Optional[int] = None,
    ) -> "ServerOptions":
        ...

    def get_default_class(self) -> Dict[str, Any]:
        ...

    def find_acceptable_class(
        self, user: "User", requested_server_options: "ServerOptions"
    ) -> Optional["ServerOptions"]:
        ...


class StorageValidatorProto(Protocol):
    def get_storage_by_id(
        self, user: "User", project_id: int, storage_id: str
    ) -> "CloudStorageConfig":
        ...

    def validate_storage_configuration(
        self, configuration: Dict[str, Any], source_path: str
    ) -> None:
        ...

    def obscure_password_fields_for_storage(self, configuration: dict[str, Any]) -> dict[str, Any]:
        ...


@dataclass
class _NotebooksConfig:
    server_options: _ServerOptionsConfig
    sessions: _SessionConfig
    amalthea: _AmaltheaConfig
    sentry: _SentryConfig
    git: _GitConfig
    k8s: _K8sConfig
    cloud_storage: _CloudStorage
    current_resource_schema_version: int = 1
    anonymous_sessions_enabled: Union[Text, bool] = False
    ssh_enabled: Union[Text, bool] = False
    service_prefix: str = "/notebooks"
    version: str = "0.0.0"
    keycloak_realm: str = "Renku"
    data_service_url: str = "http://renku-data-service"
    dummy_stores: Union[Text, bool] = False

    def __post_init__(self):
        self.anonymous_sessions_enabled = _parse_str_as_bool(self.anonymous_sessions_enabled)
        self.ssh_enabled = _parse_str_as_bool(self.ssh_enabled)
        self.dummy_stores = _parse_str_as_bool(self.dummy_stores)
        self.session_get_endpoint_annotations = _ServersGetEndpointAnnotations()
        if not self.k8s.enabled:
            return
        username_label = (
            self.session_get_endpoint_annotations.renku_annotation_prefix + "safe-username"
        )
        renku_ns_client = NamespacedK8sClient(
            self.k8s.renku_namespace,
            self.amalthea.group,
            self.amalthea.version,
            self.amalthea.plural,
        )
        session_ns_client = None
        if self.k8s.sessions_namespace:
            session_ns_client = NamespacedK8sClient(
                self.k8s.sessions_namespace,
                self.amalthea.group,
                self.amalthea.version,
                self.amalthea.plural,
            )
        js_cache = JsServerCache(self.amalthea.cache_url)
        self.k8s.client = K8sClient(
            js_cache=js_cache,
            renku_ns_client=renku_ns_client,
            session_ns_client=session_ns_client,
            username_label=username_label,
        )
        self._crc_validator = None
        self._storage_validator = None

    @property
    def crc_validator(self) -> CRCValidatorProto:
        from ..api.classes.data_service import CRCValidator, DummyCRCValidator

        if not self._crc_validator:
            if self.dummy_stores:
                self._crc_validator = DummyCRCValidator()
            else:
                self._crc_validator = CRCValidator(self.data_service_url)

        return self._crc_validator

    @property
    def storage_validator(self) -> StorageValidatorProto:
        from ..api.classes.data_service import DummyStorageValidator, StorageValidator

        if not self._storage_validator:
            if self.dummy_stores:
                self._storage_validator = DummyStorageValidator()
            else:
                self._storage_validator = StorageValidator(self.data_service_url)

        return self._storage_validator


def get_config(default_config: str) -> _NotebooksConfig:
    """Compiles the configuration for the notebook service.

    If the "CONFIG_FILE" environment variable is set then that file is read and used.
    The values from the file can be overridden by environment variables that start with
    "NB_" followed by the appropriate name. Refer to the dataconf documentation about
    how to set nested or list values. Although more complicated values are more easily set through
    a config file than environment variables.
    """
    config_file = os.getenv("CONFIG_FILE")
    config = dataconf.multi.string(default_config)
    if config_file:
        config = config.file(config_file)
    notebooks_config: _NotebooksConfig = config.env("NB_").on(_NotebooksConfig)
    return notebooks_config


default_config = """
server_options {
    defaults_path = tests/unit/dummy_server_defaults.json
    ui_choices_path = tests/unit/dummy_server_options.json
}
sessions {
    culling {
        registered {
            idle_seconds = 86400
            max_age_seconds = 0
            pending_seconds = 0
            failed_seconds = 0
            hibernated_seconds = 259200
        }
        anonymous {
            idle_seconds = 43200
            max_age_seconds = 0
            pending_seconds = 0
            failed_seconds = 0
            hibernated_seconds = 1
        }
    }
    default_image = renku/singleuser:latest
    git_proxy {
        port = 8080
        health_port = 8081
        image = "renku/git-https-proxy:latest"
        sentry = {
            enabled = false
        }
        renku_client_id = "renku"
        renku_client_secret = "renku-client-secret"
    }
    git_clone {
        image = "renku/git-clone:latest"
        sentry = {
            enabled = false
        }
    }
    git_rpc_server {
        host = "0.0.0.0"
        port = 4000
        image= "renku/git-rpc-server:latest"
        sentry = {
            enabled = false
        }
    }
    ingress = {
        annotations = "{}"
    }
    ca_certs {
        image = "renku/certificates:latest"
        path = "/usr/local/share/ca-certificates"
        secrets = "[]"
    }
    oidc {
        client_id = renku-jupyterserver
        allow_unverified_email = false
        config_url = /auth/realms/Renku/.well-known/openid-configuration
    }
    storage {
        pvs_enabled: true
    }
    containers {
        anonymous = [
            jupyter-server,
            passthrough-proxy,
            git-proxy,
        ]
        registered = [
            jupyter-server,
            oauth2-proxy,
            git-proxy,
            git-sidecar,
        ]
    }
    ssh {}
    enforce_cpu_limits: off
    termination_warning_duration_seconds: 43200
    image_default_workdir: /home/jovyan
    node_selector: "{}"
    affinity: "{}"
    tolerations: "[]"
}
amalthea {
    group = amalthea.dev
    version = v1alpha1
    plural = jupyterservers
    cache_url = http://renku-k8s-watcher
}
sentry {
    enabled = false
    sample_rate = 0.2
}
git {
    url = https://gitlab.com
    registry = registry.gitlab.com
}
k8s {
    enabled = true
    renku_namespace = renku
}
cloud_storage {
    enabled = false
    mount_folder = /cloudstorage
}
anonymous_sessions_enabled = false
ssh_enabled = false
service_prefix = /notebooks
version = 0.0.0
keycloak_realm = Renku
data_service_url = http://renku-data-service
"""

config = get_config(default_config)
__all__ = ["config"]


# NOTE: We don't allow hibernating anonymous users' sessions. However, when these sessions are
# culled, they are hibernated automatically by Amalthea. To delete them as quickly as possible
# after hibernation, we set the threshold to the minimum possible value. Since zero means don't
# delete, 1 is the minimum threshold value.
config.sessions.culling.anonymous.hibernated_seconds = 1
