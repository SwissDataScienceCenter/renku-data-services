"""Patches for the git proxy container."""

import json
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from renku_data_services.notebooks.api.amalthea_patches.utils import get_certificates_volume_mounts
from renku_data_services.notebooks.api.classes.user import AnonymousUser

if TYPE_CHECKING:
    from renku_data_services.notebooks.api.classes.server import UserServer


def main(server: "UserServer") -> list[dict[str, Any]]:
    """The patch that adds the git proxy container to a session statefulset."""
    user_is_anonymous = isinstance(server.user, AnonymousUser)
    if user_is_anonymous or not server.repositories:
        return []

    etc_cert_volume_mount = get_certificates_volume_mounts(
        server.config,
        custom_certs=False,
        etc_certs=True,
        read_only_etc_certs=True,
    )
    patches = []

    prefix = "GIT_PROXY_"
    env = [
        {"name": f"{prefix}PORT", "value": str(server.config.sessions.git_proxy.port)},
        {"name": f"{prefix}HEALTH_PORT", "value": str(server.config.sessions.git_proxy.health_port)},
        {
            "name": f"{prefix}ANONYMOUS_SESSION",
            "value": "true" if user_is_anonymous else "false",
        },
        {"name": f"{prefix}RENKU_ACCESS_TOKEN", "value": str(server.user.access_token)},
        {"name": f"{prefix}RENKU_REFRESH_TOKEN", "value": str(server.user.refresh_token)},
        {"name": f"{prefix}RENKU_REALM", "value": server.config.keycloak_realm},
        {
            "name": f"{prefix}RENKU_CLIENT_ID",
            "value": str(server.config.sessions.git_proxy.renku_client_id),
        },
        {
            "name": f"{prefix}RENKU_CLIENT_SECRET",
            "value": str(server.config.sessions.git_proxy.renku_client_secret),
        },
        {"name": f"{prefix}RENKU_URL", "value": "https://" + server.config.sessions.ingress.host},
        {
            "name": f"{prefix}REPOSITORIES",
            "value": json.dumps([asdict(repo) for repo in server.repositories]),
        },
        {
            "name": f"{prefix}PROVIDERS",
            "value": json.dumps(
                [dict(id=provider.id, access_token_url=provider.access_token_url) for provider in server.git_providers]
            ),
        },
    ]

    patches.append(
        {
            "type": "application/json-patch+json",
            "patch": [
                {
                    "op": "add",
                    "path": "/statefulset/spec/template/spec/containers/-",
                    "value": {
                        "image": server.config.sessions.git_proxy.image,
                        "securityContext": {
                            "fsGroup": 100,
                            "runAsGroup": 1000,
                            "runAsUser": 1000,
                            "allowPrivilegeEscalation": False,
                            "runAsNonRoot": True,
                        },
                        "name": "git-proxy",
                        "env": env,
                        "livenessProbe": {
                            "httpGet": {
                                "path": "/health",
                                "port": server.config.sessions.git_proxy.health_port,
                            },
                            "initialDelaySeconds": 3,
                        },
                        "readinessProbe": {
                            "httpGet": {
                                "path": "/health",
                                "port": server.config.sessions.git_proxy.health_port,
                            },
                            "initialDelaySeconds": 3,
                        },
                        "volumeMounts": etc_cert_volume_mount,
                        "resources": {
                            "requests": {"memory": "16Mi", "cpu": "50m"},
                        },
                    },
                }
            ],
        }
    )
    return patches
