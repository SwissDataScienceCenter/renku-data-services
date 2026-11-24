"""Patches for the git proxy container."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Final

from kubernetes import client

from renku_data_services.authn.renku import RenkuSelfTokenMint
from renku_data_services.base_models.core import AnonymousAPIUser, AuthenticatedAPIUser
from renku_data_services.notebooks.api.amalthea_patches.utils import get_certificates_volume_mounts
from renku_data_services.notebooks.api.classes.repository import GitProvider, Repository
from renku_data_services.notebooks.config import NotebooksConfig

REFRESH_CHECK_PERIOD_SECONDS: Final[int] = 60
"""The refresh period used for keeping the Renku refresh token alive."""


async def main_container(
    server_name: str,
    user: AnonymousAPIUser | AuthenticatedAPIUser,
    config: NotebooksConfig,
    repositories: list[Repository],
    git_providers: list[GitProvider],
    internal_token_mint: RenkuSelfTokenMint,
) -> client.V1Container | None:
    """The patch that adds the git proxy container to a session statefulset."""
    if not user.is_authenticated or not repositories or user.access_token is None:
        return None

    etc_cert_volume_mount = get_certificates_volume_mounts(
        config,
        custom_certs=False,
        etc_certs=True,
        read_only_etc_certs=True,
    )

    internal_token_scope = f"session:{server_name}"
    internal_access_token = internal_token_mint.create_access_token(user=user, scope=internal_token_scope)
    internal_refresh_token = internal_token_mint.create_refresh_token(user=user, scope=internal_token_scope)

    prefix = "GIT_PROXY_"
    env = [
        client.V1EnvVar(name=f"{prefix}PORT", value=str(config.sessions.git_proxy.port)),
        client.V1EnvVar(name=f"{prefix}HEALTH_PORT", value=str(config.sessions.git_proxy.health_port)),
        client.V1EnvVar(
            name=f"{prefix}ANONYMOUS_SESSION",
            value="false" if user.is_authenticated else "true",
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
        client.V1EnvVar(name=f"{prefix}RENKU_AUTHENTICATION_VERSION", value="v2"),
        client.V1EnvVar(name=f"{prefix}RENKU_ACCESS_TOKEN", value=internal_access_token),
        client.V1EnvVar(name=f"{prefix}RENKU_REFRESH_TOKEN", value=internal_refresh_token),
        client.V1EnvVar(
            name=f"{prefix}RENKU_TOKEN_URL",
            value=f"https://{config.sessions.ingress.host}/api/data/internal/authentication/token",
        ),
        client.V1EnvVar(
            name=f"{prefix}REFRESH_CHECK_PERIOD_SECONDS",
            value=f"{REFRESH_CHECK_PERIOD_SECONDS}",
        ),
    ]
    container = client.V1Container(
        image=config.sessions.git_proxy.image,
        args=config.sessions.git_proxy.args,
        security_context={
            "runAsGroup": 1000,
            "runAsUser": 1000,
            "allowPrivilegeEscalation": False,
            "runAsNonRoot": True,
            "capabilities": {"drop": ["ALL"]},
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
