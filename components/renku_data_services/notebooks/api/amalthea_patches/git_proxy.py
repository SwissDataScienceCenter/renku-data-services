from flask import current_app

from ..classes.user import RegisteredUser
from .utils import get_certificates_volume_mounts


def main(server):
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
                        "image": current_app.config["GIT_HTTPS_PROXY_IMAGE"],
                        "name": "git-proxy",
                        "env": [
                            {
                                "name": "REPOSITORY_URL",
                                "value": server.gl_project.http_url_to_repo,
                            },
                            {"name": "MITM_PROXY_PORT", "value": "8080"},
                            {"name": "HEALTH_PORT", "value": "8081"},
                            {
                                "name": "GITLAB_OAUTH_TOKEN",
                                "value": server._user.git_token,
                            },
                            {
                                "name": "ANONYMOUS_SESSION",
                                "value": (
                                    "false"
                                    if type(server._user) is RegisteredUser
                                    else "true"
                                ),
                            },
                        ],
                        "livenessProbe": {
                            "httpGet": {"path": "/health", "port": 8081},
                            "initialDelaySeconds": 3,
                        },
                        "readinessProbe": {
                            "httpGet": {"path": "/health", "port": 8081},
                            "initialDelaySeconds": 3,
                        },
                        "volumeMounts": etc_cert_volume_mount,
                    },
                }
            ],
        }
    )
    return patches
