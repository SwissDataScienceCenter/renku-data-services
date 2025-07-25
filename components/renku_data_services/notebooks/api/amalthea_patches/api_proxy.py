"""Patches for the api proxy container."""

from typing import TYPE_CHECKING

from kubernetes import client

from renku_data_services.base_models.core import AnonymousAPIUser, AuthenticatedAPIUser
from renku_data_services.notebooks.api.amalthea_patches.utils import get_certificates_volume_mounts
from renku_data_services.notebooks.config import NotebooksConfig

if TYPE_CHECKING:
    # NOTE: If these are directly imported then you get circular imports.
    pass


def main_container(
    session_id: str,
    user: AnonymousAPIUser | AuthenticatedAPIUser,
    config: NotebooksConfig,
) -> client.V1Container | None:
    """The patch that adds the api proxy container to a session statefulset."""
    if not user.is_authenticated or user.access_token is None or user.refresh_token is None:
        return None

    etc_cert_volume_mount = get_certificates_volume_mounts(
        config,
        custom_certs=False,
        etc_certs=True,
        read_only_etc_certs=True,
    )

    prefix = "API_PROXY_"
    env = [
        client.V1EnvVar(name=f"{prefix}HOST", value=""),
        client.V1EnvVar(name=f"{prefix}PORT", value="58080"),
        client.V1EnvVar(name=f"{prefix}SESSION_ID", value=session_id),
        client.V1EnvVar(name=f"{prefix}RENKU_ACCESS_TOKEN", value=str(user.access_token)),
        client.V1EnvVar(name=f"{prefix}RENKU_REFRESH_TOKEN", value=str(user.refresh_token)),
        client.V1EnvVar(name=f"{prefix}RENKU_REALM", value=config.keycloak_realm),
        client.V1EnvVar(
            name=f"{prefix}RENKU_CLIENT_ID",
            value=str(config.sessions.git_proxy.renku_client_id),
        ),
        client.V1EnvVar(
            name=f"{prefix}RENKU_CLIENT_SECRET",
            value=str(config.sessions.git_proxy.renku_client_secret),
        ),
        client.V1EnvVar(name=f"{prefix}RENKU_URL", value="https://" + config.sessions.ingress.host),
    ]
    container = client.V1Container(
        image="leafty/test:api-proxy-8b05fcca",
        security_context={
            "runAsGroup": 1000,
            "runAsUser": 1000,
            "allowPrivilegeEscalation": False,
            "runAsNonRoot": True,
        },
        name="api-proxy",
        env=env,
        liveness_probe={
            "httpGet": {
                "path": "/health",
                "port": 58080,
            },
            "initialDelaySeconds": 3,
        },
        readiness_probe={
            "httpGet": {
                "path": "/health",
                "port": 58080,
            },
            "initialDelaySeconds": 3,
        },
        volume_mounts=etc_cert_volume_mount,
        resources={
            "requests": {"memory": "16Mi", "cpu": "50m"},
        },
    )
    return container
