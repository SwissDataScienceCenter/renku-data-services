from dataclasses import dataclass
import dataconf
import os
from typing import Text, Union

from .dynamic import (
    _ServerOptionsConfig,
    _SessionConfig,
    _AmaltheaConfig,
    _SentryConfig,
    _GitConfig,
    _K8sConfig,
    _parse_str_as_bool,
)
from .static import _ServersGetEndpointAnnotations


@dataclass
class _NotebooksConfig:
    server_options: _ServerOptionsConfig
    sessions: _SessionConfig
    amalthea: _AmaltheaConfig
    sentry: _SentryConfig
    git: _GitConfig
    k8s: _K8sConfig
    current_resource_schema_version: int = 1
    s3_mounts_enabled: Union[Text, bool] = False
    anonymous_sessions_enabled: Union[Text, bool] = False
    service_prefix: str = "/notebooks"
    version: str = "0.0.0"

    def __post_init__(self):
        self.s3_mounts_enabled = _parse_str_as_bool(self.s3_mounts_enabled)
        self.anonymous_sessions_enabled = _parse_str_as_bool(
            self.anonymous_sessions_enabled
        )
        self.session_get_endpoint_annotations = _ServersGetEndpointAnnotations()


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
    config: _NotebooksConfig = config.env("NB_").on(_NotebooksConfig)
    return config


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
        }
        anonymous {
            idle_seconds = 86400
            max_age_seconds = 0
            pending_seconds = 0
            failed_seconds = 0
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
    enforce_cpu_limits: false
    autosave_minimum_lfs_file_size_bytes: 1000000
    termination_grace_period_seconds: 600
    image_default_workdir: /home/jovyan
    node_selector: "{}"
    affinity: "{}"
    tolerations: "[]"
    container_order_anonymous = [
        jupyter-server
    ]
    container_order_registered = [
        jupyter-server
        oauth2-proxy
    ]
}
amalthea {
    group = amalthea.dev
    version = v1alpha1
    plural = jupyterservers
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
}
s3_mounts_enabled = false
anonymous_sessions_enabled = false
service_prefix = /notebooks
version = 0.0.0
"""

config = get_config(default_config)
__all__ = ["config"]
