"""Patches for the git proxy container."""

import json
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from kubernetes import client

from renku_data_services.base_models.core import AnonymousAPIUser, AuthenticatedAPIUser
from renku_data_services.notebooks.api.amalthea_patches.utils import get_certificates_volume_mounts
from renku_data_services.notebooks.api.classes.repository import GitProvider, Repository
from renku_data_services.notebooks.config import _NotebooksConfig

if TYPE_CHECKING:
    # NOTE: If these are directly imported then you get circular imports.
    from renku_data_services.notebooks.api.classes.server import UserServer


async def main_container(
    user: AnonymousAPIUser | AuthenticatedAPIUser,
    config: _NotebooksConfig,
    repositories: list[Repository],
    git_providers: list[GitProvider],
) -> client.V1Container | None:
    """The patch that adds the git proxy container to a session statefulset."""
    if not user.is_authenticated or not repositories or user.access_token is None or user.refresh_token is None:
        return None

    etc_cert_volume_mount = get_certificates_volume_mounts(
        config,
        custom_certs=False,
        etc_certs=True,
        read_only_etc_certs=True,
    )

    prefix = "GIT_PROXY_"
    env = [
        client.V1EnvVar(name=f"{prefix}PORT", value=str(config.sessions.git_proxy.port)),
        client.V1EnvVar(name=f"{prefix}HEALTH_PORT", value=str(config.sessions.git_proxy.health_port)),
        client.V1EnvVar(
            name=f"{prefix}ANONYMOUS_SESSION",
            value="false" if user.is_authenticated else "true",
        ),
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
        image=config.sessions.git_proxy.image,
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
                "port": config.sessions.git_proxy.health_port,
            },
            "initialDelaySeconds": 3,
        },
        readiness_probe={
            "httpGet": {
                "path": "/health",
                "port": config.sessions.git_proxy.health_port,
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

    git_providers = await server.git_providers()
    container = await main_container(server.user, server.config, repositories, git_providers)
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
