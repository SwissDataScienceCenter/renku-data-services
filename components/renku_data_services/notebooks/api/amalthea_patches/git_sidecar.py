"""Patches for the git sidecar container."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # NOTE: If these are directly imported then you get circular imports.
    from renku_data_services.notebooks.api.classes.server import UserServer


async def main(server: UserServer) -> list[dict[str, Any]]:
    """Adds the git sidecar container to the session statefulset."""
    # NOTE: Sessions can be persisted only for registered users
    if not server.user.is_authenticated:
        return []
    repositories = await server.repositories()
    if not repositories:
        return []

    gitlab_project = getattr(server, "gitlab_project", None)
    gl_project_path = gitlab_project.path if gitlab_project else None
    commit_sha = getattr(server, "commit_sha", None)

    volume_mount = {
        "mountPath": server.work_dir.as_posix(),
        "name": "workspace",
    }
    if gl_project_path:
        volume_mount["subPath"] = f"{gl_project_path}"

    # noinspection PyListCreation
    patches = [
        {
            "type": "application/json-patch+json",
            "patch": [
                {
                    "op": "add",
                    "path": "/statefulset/spec/template/spec/containers/-",
                    "value": {
                        "image": server.config.sessions.git_rpc_server.image,
                        "name": "git-sidecar",
                        "ports": [
                            {
                                "containerPort": server.config.sessions.git_rpc_server.port,
                                "name": "git-port",
                                "protocol": "TCP",
                            }
                        ],
                        "resources": {
                            "requests": {"memory": "84Mi", "cpu": "100m"},
                        },
                        "env": [
                            {
                                "name": "GIT_RPC_MOUNT_PATH",
                                "value": server.work_dir.as_posix(),
                            },
                            {
                                "name": "GIT_RPC_PORT",
                                "value": str(server.config.sessions.git_rpc_server.port),
                            },
                            {
                                "name": "GIT_RPC_HOST",
                                "value": server.config.sessions.git_rpc_server.host,
                            },
                            {
                                "name": "GIT_RPC_URL_PREFIX",
                                "value": f"/sessions/{server.server_name}/sidecar/",
                            },
                            {
                                "name": "GIT_RPC_SENTRY__ENABLED",
                                "value": str(server.config.sessions.git_rpc_server.sentry.enabled).lower(),
                            },
                            {
                                "name": "GIT_RPC_SENTRY__DSN",
                                "value": server.config.sessions.git_rpc_server.sentry.dsn,
                            },
                            {
                                "name": "GIT_RPC_SENTRY__ENVIRONMENT",
                                "value": server.config.sessions.git_rpc_server.sentry.env,
                            },
                            {
                                "name": "GIT_RPC_SENTRY__SAMPLE_RATE",
                                "value": str(server.config.sessions.git_rpc_server.sentry.sample_rate),
                            },
                            {
                                "name": "SENTRY_RELEASE",
                                "value": os.environ.get("SENTRY_RELEASE"),
                            },
                            {
                                "name": "CI_COMMIT_SHA",
                                "value": f"{commit_sha}",
                            },
                            {
                                "name": "RENKU_USERNAME",
                                "value": f"{server.user.id}",
                            },
                            {
                                "name": "GIT_RPC_GIT_PROXY_HEALTH_PORT",
                                "value": str(server.config.sessions.git_proxy.health_port),
                            },
                        ],
                        "securityContext": {
                            "allowPrivilegeEscalation": False,
                            "runAsGroup": 1000,
                            "runAsUser": 1000,
                            "runAsNonRoot": True,
                            "capabilities": {"drop": ["ALL"]},
                        },
                        "volumeMounts": [volume_mount],
                        "livenessProbe": {
                            "httpGet": {
                                "port": server.config.sessions.git_rpc_server.port,
                                "path": f"/sessions/{server.server_name}/sidecar/health",
                            },
                            "periodSeconds": 10,
                            "failureThreshold": 2,
                        },
                        "readinessProbe": {
                            "httpGet": {
                                "port": server.config.sessions.git_rpc_server.port,
                                "path": f"/sessions/{server.server_name}/sidecar/health",
                            },
                            "periodSeconds": 10,
                            "failureThreshold": 6,
                        },
                        "startupProbe": {
                            "httpGet": {
                                "port": server.config.sessions.git_rpc_server.port,
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
                        f"--upstream=http://127.0.0.1:{server.config.sessions.git_rpc_server.port}"
                        f"/sessions/{server.server_name}/sidecar/"
                    ),
                },
                {
                    "op": "add",
                    "path": "/statefulset/spec/template/spec/containers/1/args/-",
                    "value": f"--skip-auth-route=^/sessions/{server.server_name}/sidecar/health$",
                },
                {
                    "op": "add",
                    "path": "/statefulset/spec/template/spec/containers/1/args/-",
                    "value": f"--skip-auth-route=^/sessions/{server.server_name}/sidecar/health/$",
                },
                {
                    "op": "add",
                    "path": "/statefulset/spec/template/spec/containers/1/args/-",
                    "value": "--skip-jwt-bearer-tokens=true",
                },
                {
                    "op": "add",
                    "path": "/statefulset/spec/template/spec/containers/1/args/-",
                    "value": f"--skip-auth-route=^/sessions/{server.server_name}/sidecar/jsonrpc/map$",
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
                            "namespace": server.k8s_namespace(),
                        },
                        "spec": {
                            "ports": [
                                {
                                    "name": "http",
                                    "port": 80,
                                    "protocol": "TCP",
                                    "targetPort": server.config.sessions.git_rpc_server.port,
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
