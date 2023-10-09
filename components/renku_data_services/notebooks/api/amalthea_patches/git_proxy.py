from typing import TYPE_CHECKING

from ...config import config
from ..classes.user import RegisteredUser
from .utils import get_certificates_volume_mounts

if TYPE_CHECKING:
    from renku_notebooks.api.classes.server import UserServer


def main(server: "UserServer"):
    etc_cert_volume_mount = get_certificates_volume_mounts(
        custom_certs=False,
        etc_certs=True,
        read_only_etc_certs=True,
    )
    patches = []
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
                        "env": [
                            {
                                "name": "REPOSITORY_URL",
                                "value": server.gl_project.http_url_to_repo,
                            },
                            {
                                "name": "GIT_PROXY_PORT",
                                "value": str(config.sessions.git_proxy.port),
                            },
                            {
                                "name": "GIT_PROXY_HEALTH_PORT",
                                "value": str(config.sessions.git_proxy.health_port),
                            },
                            {
                                "name": "GITLAB_OAUTH_TOKEN",
                                "value": str(server._user.git_token),
                            },
                            {
                                "name": "GITLAB_OAUTH_TOKEN_EXPIRES_AT",
                                "value": str(server._user.git_token_expires_at),
                            },
                            {
                                "name": "RENKU_ACCESS_TOKEN",
                                "value": str(server._user.access_token),
                            },
                            {
                                "name": "RENKU_REFRESH_TOKEN",
                                "value": str(server._user.refresh_token),
                            },
                            {
                                "name": "RENKU_REALM",
                                "value": config.keycloak_realm,
                            },
                            {
                                "name": "RENKU_CLIENT_ID",
                                "value": str(config.sessions.git_proxy.renku_client_id),
                            },
                            {
                                "name": "RENKU_CLIENT_SECRET",
                                "value": str(config.sessions.git_proxy.renku_client_secret),
                            },
                            {
                                "name": "RENKU_URL",
                                "value": "https://" + config.sessions.ingress.host,
                            },
                            {
                                "name": "ANONYMOUS_SESSION",
                                "value": (
                                    "false" if type(server._user) is RegisteredUser else "true"
                                ),
                            },
                        ],
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
