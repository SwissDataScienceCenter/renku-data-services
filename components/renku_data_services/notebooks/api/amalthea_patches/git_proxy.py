"""Patches for the git proxy container."""

import json
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from kubernetes import client

from renku_data_services.notebooks.api.amalthea_patches.utils import get_certificates_volume_mounts

if TYPE_CHECKING:
    # NOTE: If these are directly imported then you get circular imports.
    from renku_data_services.notebooks.api.classes.server import UserServer


async def main_container(server: "UserServer") -> client.V1Container | None:
    """The patch that adds the git proxy container to a session statefulset."""
    repositories = await server.repositories()
    if not server.user.is_authenticated or not repositories:
        return None

    etc_cert_volume_mount = get_certificates_volume_mounts(
        server.config,
        custom_certs=False,
        etc_certs=True,
        read_only_etc_certs=True,
    )

    prefix = "GIT_PROXY_"
    git_providers = await server.git_providers()
    repositories = await server.repositories()
    env = [
        client.V1EnvVar(name=f"{prefix}PORT", value=str(server.config.sessions.git_proxy.port)),
        client.V1EnvVar(name=f"{prefix}HEALTH_PORT", value=str(server.config.sessions.git_proxy.health_port)),
        client.V1EnvVar(
            name=f"{prefix}ANONYMOUS_SESSION",
            value="false" if server.user.is_authenticated else "true",
        ),
        client.V1EnvVar(name=f"{prefix}RENKU_ACCESS_TOKEN", value=str(server.user.access_token)),
        client.V1EnvVar(name=f"{prefix}RENKU_REFRESH_TOKEN", value=str(server.user.refresh_token)),
        client.V1EnvVar(name=f"{prefix}RENKU_REALM", value=server.config.keycloak_realm),
        client.V1EnvVar(
            name=f"{prefix}RENKU_CLIENT_ID",
            value=str(server.config.sessions.git_proxy.renku_client_id),
        ),
        client.V1EnvVar(
            name=f"{prefix}RENKU_CLIENT_SECRET",
            value=str(server.config.sessions.git_proxy.renku_client_secret),
        ),
        client.V1EnvVar(name=f"{prefix}RENKU_URL", value="https://" + server.config.sessions.ingress.host),
        client.V1EnvVar(
            name=f"{prefix}REPOSITORIES",
            value=json.dumps([asdict(repo) for repo in repositories]),
        ),
        client.V1EnvVar(
            name=f"{prefix}PROVIDERS",
            value=json.dumps(
                [dict(id=provider.id, access_token_url=provider.access_token_url) for provider in git_providers]
            ),
        ),
    ]
    container = client.V1Container(
        image=server.config.sessions.git_proxy.image,
        security_context={
            "fsGroup": 100,
            "runAsGroup": 1000,
            "runAsUser": 1000,
            "allowPrivilegeEscalation": False,
            "runAsNonRoot": True,
        },
        name="git-proxy",
        env=env,
        liveness_probe={
            "httpGet": {
                "path": "/health",
                "port": server.config.sessions.git_proxy.health_port,
            },
            "initialDelaySeconds": 3,
        },
        readiness_probe={
            "httpGet": {
                "path": "/health",
                "port": server.config.sessions.git_proxy.health_port,
            },
            "initialDelaySeconds": 3,
        },
        volume_mounts=etc_cert_volume_mount,
        resources={
            "requests": {"memory": "16Mi", "cpu": "50m"},
        },
    )
    return container


async def main(server: "UserServer") -> list[dict[str, Any]]:
    """The patch that adds the git proxy container to a session statefulset."""
    repositories = await server.repositories()
    if not server.user.is_authenticated or not repositories:
        return []

    container = await main_container(server)
    if not container:
        return []

    patches = []

    patches.append(
        {
            "type": "application/json-patch+json",
            "patch": [
                {
                    "op": "add",
                    "path": "/statefulset/spec/template/spec/containers/-",
                    "value": client.ApiClient().sanitize_for_serialization(container),
                },
            ],
        }
    )
    return patches
