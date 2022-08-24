import os
from typing import TYPE_CHECKING

from ..classes.user import RegisteredUser
from ...config import config

if TYPE_CHECKING:
    from renku_notebooks.api.classes.server import UserServer


def main(server: "UserServer"):
    # NOTE: Autosaves can be created only for registered users
    if type(server._user) is not RegisteredUser:
        return []
    lifecycle = {
        "preStop": {
            "exec": {
                "command": [
                    "poetry",
                    "run",
                    "python",
                    "-m",
                    "git_services.sidecar.run_command",
                    "autosave",
                ]
            }
        }
    }
    patches = [
        {
            "type": "application/json-patch+json",
            "patch": [
                {
                    "op": "add",
                    "path": "/statefulset/spec/template/spec/containers/-",
                    "value": {
                        "image": config.sessions.git_rpc_server.image,
                        "name": "git-sidecar",
                        "ports": [
                            {
                                "containerPort": config.sessions.git_rpc_server.port,
                                "name": "git-port",
                                "protocol": "TCP",
                            }
                        ],
                        "resources": {
                            "requests": {"memory": "84Mi", "cpu": "100m"},
                            "limits": {"memory": "168Mi", "cpu": "200m"},
                        },
                        "env": [
                            {
                                "name": "GIT_RPC_MOUNT_PATH",
                                "value": f"/work/{server.gl_project.path}",
                            },
                            {
                                "name": "GIT_RPC_PORT",
                                "value": str(config.sessions.git_rpc_server.port),
                            },
                            {
                                "name": "GIT_RPC_HOST",
                                "value": config.sessions.git_rpc_server.host,
                            },
                            {
                                "name": "GIT_RPC_URL_PREFIX",
                                "value": f"/sessions/{server.server_name}/sidecar/",
                            },
                            {
                                "name": "GIT_RPC_SENTRY__ENABLED",
                                "value": str(
                                    config.sessions.git_rpc_server.sentry.enabled
                                ).lower(),
                            },
                            {
                                "name": "GIT_RPC_SENTRY__DSN",
                                "value": config.sessions.git_rpc_server.sentry.dsn,
                            },
                            {
                                "name": "GIT_RPC_SENTRY__ENVIRONMENT",
                                "value": config.sessions.git_rpc_server.sentry.env,
                            },
                            {
                                "name": "GIT_RPC_SENTRY__SAMPLE_RATE",
                                "value": str(
                                    config.sessions.git_rpc_server.sentry.sample_rate
                                ),
                            },
                            {
                                "name": "SENTRY_RELEASE",
                                "value": os.environ.get("SENTRY_RELEASE"),
                            },
                            {
                                "name": "CI_COMMIT_SHA",
                                "value": f"{server.commit_sha}",
                            },
                            {
                                "name": "RENKU_USERNAME",
                                "value": f"{server._user.username}",
                            },
                            # NOTE: The git proxy health port is also used to signal that the proxy
                            # can safely shut down after any autosave branches have been properly
                            # created.
                            {
                                "name": "GIT_RPC_GIT_PROXY_HEALTH_PORT",
                                "value": str(config.sessions.git_proxy.health_port),
                            },
                            {
                                "name": "AUTOSAVE_MINIMUM_LFS_FILE_SIZE_BYTES",
                                "value": str(
                                    config.sessions.autosave_minimum_lfs_file_size_bytes
                                ),
                            },
                        ],
                        # NOTE: Autosave Branch creation
                        "lifecycle": lifecycle,
                        "securityContext": {
                            "allowPrivilegeEscalation": False,
                            "fsGroup": 100,
                            "runAsGroup": 1000,
                            "runAsUser": 1000,
                            "runAsNonRoot": True,
                        },
                        "volumeMounts": [
                            {
                                "mountPath": f"/work/{server.gl_project.path}/",
                                "name": "workspace",
                                "subPath": f"{server.gl_project.path}/",
                            }
                        ],
                        "livenessProbe": {
                            "httpGet": {
                                "port": config.sessions.git_rpc_server.port,
                                "path": f"/sessions/{server.server_name}/sidecar/health",
                            },
                            "periodSeconds": 10,
                            "failureThreshold": 2,
                        },
                        "readinessProbe": {
                            "httpGet": {
                                "port": config.sessions.git_rpc_server.port,
                                "path": f"/sessions/{server.server_name}/sidecar/health",
                            },
                            "periodSeconds": 10,
                            "failureThreshold": 6,
                        },
                        "startupProbe": {
                            "httpGet": {
                                "port": config.sessions.git_rpc_server.port,
                                "path": f"/sessions/{server.server_name}/sidecar/health",
                            },
                            "periodSeconds": 10,
                            "failureThreshold": 30,
                        },
                    },
                }
            ],
        }
    ]
    # NOTE: The oauth2proxy is used to authenticate requests for the sidecar
    patches.append(
        {
            "type": "application/json-patch+json",
            "patch": [
                {
                    "op": "replace",
                    "path": "/statefulset/spec/template/spec/containers/1/args/6",
                    "value": f"--upstream=http://127.0.0.1:8888/sessions/{server.server_name}/",
                },
                {
                    "op": "add",
                    "path": "/statefulset/spec/template/spec/containers/1/args/-",
                    "value": (
                        f"--upstream=http://127.0.0.1:{config.sessions.git_rpc_server.port}"
                        f"/sessions/{server.server_name}/sidecar/"
                    ),
                },
                {
                    "op": "add",
                    "path": "/statefulset/spec/template/spec/containers/1/args/-",
                    "value": (
                        f"--skip-auth-route=^/sessions/{server.server_name}/sidecar/health$"
                    ),
                },
                {
                    "op": "add",
                    "path": "/statefulset/spec/template/spec/containers/1/args/-",
                    "value": (
                        f"--skip-auth-route=^/sessions/{server.server_name}/sidecar/health/$"
                    ),
                },
                {
                    "op": "add",
                    "path": "/statefulset/spec/template/spec/containers/1/args/-",
                    "value": "--skip-jwt-bearer-tokens=true",
                },
                {
                    "op": "add",
                    "path": "/statefulset/spec/template/spec/containers/1/args/-",
                    "value": (
                        f"--skip-auth-route=^/sessions/{server.server_name}/sidecar/jsonrpc/map$"
                    ),
                },
                {
                    "op": "add",
                    "path": "/statefulset/spec/template/spec/containers/1/image",
                    "value": "bitnami/oauth2-proxy:7.3.0",
                },
                {
                    "op": "add",
                    "path": "/statefulset/spec/template/spec/containers/1/args/-",
                    "value": "--oidc-extra-audience=renku",
                },
            ],
        }
    )
    # INFO: Add a k8s service so that the RPC server can be directly reached by the ui server
    patches.append(
        {
            "type": "application/json-patch+json",
            "patch": [
                {
                    "op": "add",
                    "path": "/serviceRpcServer",
                    "value": {
                        "apiVersion": "v1",
                        "kind": "Service",
                        "metadata": {
                            "name": f"{server.server_name}-rpc-server",
                            "namespace": config.k8s.namespace,
                        },
                        "spec": {
                            "ports": [
                                {
                                    "name": "http",
                                    "port": 80,
                                    "protocol": "TCP",
                                    "targetPort": config.sessions.git_rpc_server.port,
                                },
                            ],
                            "selector": {
                                "app": server.server_name,
                            },
                        },
                    },
                },
            ],
        }
    )

    return patches
