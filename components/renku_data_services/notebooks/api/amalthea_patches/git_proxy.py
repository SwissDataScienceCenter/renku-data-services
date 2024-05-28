import json
from dataclasses import asdict
from typing import TYPE_CHECKING

from ...config import config
from .utils import get_certificates_volume_mounts

if TYPE_CHECKING:
    from renku_notebooks.api.classes.server import UserServer


def main(server: "UserServer"):
    if server.user.anonymous or not server.repositories:
        return []

    etc_cert_volume_mount = get_certificates_volume_mounts(
        custom_certs=False,
        etc_certs=True,
        read_only_etc_certs=True,
    )
    patches = []

    prefix = "GIT_PROXY_"
    env = [
        {"name": f"{prefix}PORT", "value": str(config.sessions.git_proxy.port)},
        {"name": f"{prefix}HEALTH_PORT", "value": str(config.sessions.git_proxy.health_port)},
        {
            "name": f"{prefix}ANONYMOUS_SESSION",
            "value": "true" if server.user.anonymous else "false",
        },
        {"name": f"{prefix}RENKU_ACCESS_TOKEN", "value": str(server.user.access_token)},
        {"name": f"{prefix}RENKU_REFRESH_TOKEN", "value": str(server.user.refresh_token)},
        {"name": f"{prefix}RENKU_REALM", "value": config.keycloak_realm},
        {
            "name": f"{prefix}RENKU_CLIENT_ID",
            "value": str(config.sessions.git_proxy.renku_client_id),
        },
        {
            "name": f"{prefix}RENKU_CLIENT_SECRET",
            "value": str(config.sessions.git_proxy.renku_client_secret),
        },
        {"name": f"{prefix}RENKU_URL", "value": "https://" + config.sessions.ingress.host},
        {
            "name": f"{prefix}REPOSITORIES",
            "value": json.dumps([asdict(repo) for repo in server.repositories]),
        },
        {
            "name": f"{prefix}PROVIDERS",
            "value": json.dumps(
                [
                    dict(id=provider.id, access_token_url=provider.access_token_url)
                    for provider in server.git_providers
                ]
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
                        "image": config.sessions.git_proxy.image,
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
                                "port": config.sessions.git_proxy.health_port,
                            },
                            "initialDelaySeconds": 3,
                        },
                        "readinessProbe": {
                            "httpGet": {
                                "path": "/health",
                                "port": config.sessions.git_proxy.health_port,
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
