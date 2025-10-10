"""Patches for init containers."""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

from kubernetes import client

from renku_data_services.base_models.core import AnonymousAPIUser, AuthenticatedAPIUser
from renku_data_services.notebooks.api.amalthea_patches.utils import (
    get_certificates_volume_mounts,
    get_certificates_volume_mounts_unserialized,
)
from renku_data_services.notebooks.api.classes.repository import GitProvider, Repository
from renku_data_services.notebooks.config import NotebooksConfig
from renku_data_services.notebooks.crs import (
    EmptyDir,
    ExtraVolume,
    ExtraVolumeMount,
    InitContainer,
    SecretAsVolume,
)
from renku_data_services.notebooks.models import SessionExtraResources
from renku_data_services.project import constants as project_constants
from renku_data_services.project.models import SessionSecret

if TYPE_CHECKING:
    # NOTE: If these are directly imported then you get circular imports.
    from renku_data_services.notebooks.api.classes.server import UserServer


async def git_clone_container_v2(
    user: AuthenticatedAPIUser | AnonymousAPIUser,
    config: NotebooksConfig,
    repositories: list[Repository],
    git_providers: list[GitProvider],
    workspace_mount_path: PurePosixPath,
    work_dir: PurePosixPath,
    lfs_auto_fetch: bool = False,
    uid: int = 1000,
    gid: int = 1000,
) -> dict[str, Any] | None:
    """Returns the specification for the container that clones the user's repositories for new operator."""
    amalthea_session_work_volume: str = "amalthea-volume"
    if not repositories:
        return None

    etc_cert_volume_mount = get_certificates_volume_mounts(
        config,
        custom_certs=False,
        etc_certs=True,
        read_only_etc_certs=True,
    )

    prefix = "GIT_CLONE_"
    env = [
        {
            "name": f"{prefix}MOUNT_PATH",
            "value": work_dir.as_posix(),
        },
        {
            "name": f"{prefix}LFS_AUTO_FETCH",
            "value": "1" if lfs_auto_fetch else "0",
        },
        {
            "name": f"{prefix}USER__USERNAME",
            "value": user.email,
        },
        {
            "name": f"{prefix}USER__RENKU_TOKEN",
            "value": str(user.access_token),
        },
        {"name": f"{prefix}IS_GIT_PROXY_ENABLED", "value": "0" if user.is_anonymous else "1"},
        {
            "name": f"{prefix}SENTRY__ENABLED",
            "value": str(config.sessions.git_clone.sentry.enabled).lower(),
        },
        {
            "name": f"{prefix}SENTRY__DSN",
            "value": config.sessions.git_clone.sentry.dsn,
        },
        {
            "name": f"{prefix}SENTRY__ENVIRONMENT",
            "value": config.sessions.git_clone.sentry.env,
        },
        {
            "name": f"{prefix}SENTRY__SAMPLE_RATE",
            "value": str(config.sessions.git_clone.sentry.sample_rate),
        },
        {"name": "SENTRY_RELEASE", "value": os.environ.get("SENTRY_RELEASE")},
        {
            "name": "REQUESTS_CA_BUNDLE",
            "value": str(Path(etc_cert_volume_mount[0]["mountPath"]) / "ca-certificates.crt"),
        },
        {
            "name": "SSL_CERT_FILE",
            "value": str(Path(etc_cert_volume_mount[0]["mountPath"]) / "ca-certificates.crt"),
        },
    ]
    if user.is_authenticated:
        env.append({"name": f"{prefix}GIT_PROXY_PORT", "value": str(config.sessions.git_proxy.port)})
        if user.email:
            env.append(
                {"name": f"{prefix}USER__EMAIL", "value": user.email},
            )
        full_name = user.get_full_name()
        if full_name:
            env.append(
                {
                    "name": f"{prefix}USER__FULL_NAME",
                    "value": full_name,
                },
            )

    # Set up git repositories
    for idx, repo in enumerate(repositories):
        obj_env = f"{prefix}REPOSITORIES_{idx}_"
        env.append(
            {
                "name": obj_env,
                "value": json.dumps(asdict(repo)),
            }
        )

    # Set up git providers
    required_provider_ids: set[str] = {r.provider for r in repositories if r.provider}
    required_git_providers = [p for p in git_providers if p.id in required_provider_ids]
    for idx, provider in enumerate(required_git_providers):
        obj_env = f"{prefix}GIT_PROVIDERS_{idx}_"
        data = dict(id=provider.id, access_token_url=provider.access_token_url)
        env.append(
            {
                "name": obj_env,
                "value": json.dumps(data),
            }
        )

    return {
        "image": config.sessions.git_clone.image,
        "name": "git-clone",
        "resources": {
            "requests": {
                "cpu": "100m",
                "memory": "100Mi",
            }
        },
        "securityContext": {
            "allowPrivilegeEscalation": False,
            "runAsGroup": gid,
            "runAsUser": uid,
            "runAsNonRoot": True,
            "capabilities": {"drop": ["ALL"]},
        },
        "volumeMounts": [
            {
                "mountPath": workspace_mount_path.as_posix(),
                "name": amalthea_session_work_volume,
            },
            *etc_cert_volume_mount,
        ],
        "env": env,
    }


async def git_clone_container(server: UserServer) -> dict[str, Any] | None:
    """Returns the specification for the container that clones the user's repositories."""
    repositories = await server.repositories()
    if not repositories:
        return None

    etc_cert_volume_mount = get_certificates_volume_mounts(
        server.config,
        custom_certs=False,
        etc_certs=True,
        read_only_etc_certs=True,
    )

    prefix = "GIT_CLONE_"
    env = [
        {
            "name": f"{prefix}MOUNT_PATH",
            "value": server.workspace_mount_path.as_posix(),
        },
        {
            "name": f"{prefix}LFS_AUTO_FETCH",
            "value": "1" if server.server_options.lfs_auto_fetch else "0",
        },
        {
            "name": f"{prefix}USER__USERNAME",
            "value": server.user.email,
        },
        {
            "name": f"{prefix}USER__RENKU_TOKEN",
            "value": str(server.user.access_token),
        },
        {"name": f"{prefix}IS_GIT_PROXY_ENABLED", "value": "0" if server.user.is_anonymous else "1"},
        {
            "name": f"{prefix}SENTRY__ENABLED",
            "value": str(server.config.sessions.git_clone.sentry.enabled).lower(),
        },
        {
            "name": f"{prefix}SENTRY__DSN",
            "value": server.config.sessions.git_clone.sentry.dsn,
        },
        {
            "name": f"{prefix}SENTRY__ENVIRONMENT",
            "value": server.config.sessions.git_clone.sentry.env,
        },
        {
            "name": f"{prefix}SENTRY__SAMPLE_RATE",
            "value": str(server.config.sessions.git_clone.sentry.sample_rate),
        },
        {"name": "SENTRY_RELEASE", "value": os.environ.get("SENTRY_RELEASE")},
        {
            "name": "REQUESTS_CA_BUNDLE",
            "value": str(Path(etc_cert_volume_mount[0]["mountPath"]) / "ca-certificates.crt"),
        },
        {
            "name": "SSL_CERT_FILE",
            "value": str(Path(etc_cert_volume_mount[0]["mountPath"]) / "ca-certificates.crt"),
        },
    ]
    if server.user.is_authenticated:
        if server.user.email:
            env.append(
                {"name": f"{prefix}USER__EMAIL", "value": server.user.email},
            )
        full_name = server.user.get_full_name()
        if full_name:
            env.append(
                {
                    "name": f"{prefix}USER__FULL_NAME",
                    "value": full_name,
                },
            )

    # Set up git repositories
    for idx, repo in enumerate(repositories):
        obj_env = f"{prefix}REPOSITORIES_{idx}_"
        env.append(
            {
                "name": obj_env,
                "value": json.dumps(asdict(repo)),
            }
        )

    # Set up git providers
    required_git_providers = await server.required_git_providers()
    for idx, provider in enumerate(required_git_providers):
        obj_env = f"{prefix}GIT_PROVIDERS_{idx}_"
        data = dict(id=provider.id, access_token_url=provider.access_token_url)
        env.append(
            {
                "name": obj_env,
                "value": json.dumps(data),
            }
        )

    return {
        "image": server.config.sessions.git_clone.image,
        "name": "git-clone",
        "resources": {
            "requests": {
                "cpu": "100m",
                "memory": "100Mi",
            }
        },
        "securityContext": {
            "allowPrivilegeEscalation": False,
            "runAsGroup": 100,
            "runAsUser": 1000,
            "runAsNonRoot": True,
        },
        "volumeMounts": [
            {
                "mountPath": server.workspace_mount_path.as_posix(),
                "name": "workspace",
            },
            *etc_cert_volume_mount,
        ],
        "env": env,
    }


async def git_clone(server: UserServer) -> list[dict[str, Any]]:
    """The patch for the init container that clones the git repository."""
    container = await git_clone_container(server)
    if not container:
        return []
    return [
        {
            "type": "application/json-patch+json",
            "patch": [
                {
                    "op": "add",
                    "path": "/statefulset/spec/template/spec/initContainers/-",
                    "value": container,
                },
            ],
        }
    ]


def certificates_volume_mounts(config: NotebooksConfig) -> list[ExtraVolumeMount]:
    """Get the volume mounts for the CA certificates."""
    return get_certificates_volume_mounts_unserialized(
        config,
        etc_certs=True,
        custom_certs=True,
        read_only_etc_certs=True,
    )


def certificates_container(config: NotebooksConfig) -> tuple[client.V1Container, list[client.V1Volume]]:
    """The specification for the container that setups self signed CAs."""
    init_container = client.V1Container(
        name="init-certificates",
        image=config.sessions.ca_certs.image,
        volume_mounts=get_certificates_volume_mounts(
            config,
            etc_certs=True,
            custom_certs=True,
            read_only_etc_certs=False,
        ),
        security_context=client.V1SecurityContext(
            allow_privilege_escalation=False,
            run_as_group=1000,
            run_as_user=1000,
            run_as_non_root=True,
            capabilities=client.V1Capabilities(drop=["ALL"]),
        ),
        resources={
            "requests": {
                "cpu": "50m",
                "memory": "50Mi",
            }
        },
    )
    volume_etc_certs = client.V1Volume(name="etc-ssl-certs", empty_dir=client.V1EmptyDirVolumeSource(medium="Memory"))
    volume_custom_certs = client.V1Volume(
        name="custom-ca-certs",
        projected=client.V1ProjectedVolumeSource(
            default_mode=440,
            sources=[
                {"secret": {"name": secret.get("secret")}}
                for secret in config.sessions.ca_certs.secrets
                if isinstance(secret, dict) and secret.get("secret") is not None
            ],
        ),
    )
    return (init_container, [volume_etc_certs, volume_custom_certs])


def certificates(config: NotebooksConfig) -> list[dict[str, Any]]:
    """Add a container that initializes custom certificate authorities for a session."""
    container, vols = certificates_container(config)
    api_client = client.ApiClient()
    patches = [
        {
            "type": "application/json-patch+json",
            "patch": [
                {
                    "op": "add",
                    "path": "/statefulset/spec/template/spec/initContainers/-",
                    "value": api_client.sanitize_for_serialization(container),
                },
            ],
        },
    ]
    for vol in vols:
        patches.append(
            {
                "type": "application/json-patch+json",
                "patch": [
                    {
                        "op": "add",
                        "path": "/statefulset/spec/template/spec/volumes/-",
                        "value": api_client.sanitize_for_serialization(vol),
                    },
                ],
            },
        )
    return patches


def download_image_container(server: UserServer) -> client.V1Container:
    """Adds a container that does not do anything but simply downloads the session image at startup."""
    container = client.V1Container(
        name="download-image",
        image=server.image,
        command=["sh", "-c"],
        args=["exit", "0"],
        resources={
            "requests": {
                "cpu": "50m",
                "memory": "50Mi",
            }
        },
    )
    return container


def download_image(server: UserServer) -> list[dict[str, Any]]:
    """Adds a container that does not do anything but simply downloads the session image at startup."""
    container = download_image_container(server)
    api_client = client.ApiClient()
    return [
        {
            "type": "application/json-patch+json",
            "patch": [
                {
                    "op": "add",
                    "path": "/statefulset/spec/template/spec/initContainers/-",
                    "value": api_client.sanitize_for_serialization(container),
                },
            ],
        },
    ]


def user_secrets_extras(
    user: AuthenticatedAPIUser | AnonymousAPIUser,
    config: NotebooksConfig,
    secrets_mount_directory: str,
    k8s_secret_name: str,
    session_secrets: list[SessionSecret],
) -> SessionExtraResources | None:
    """The session extras which decrypts user secrets to be mounted in the session."""
    if not session_secrets or user.is_anonymous:
        return None

    volume_k8s_secrets = ExtraVolume(
        name=f"{k8s_secret_name}-volume",
        secret=SecretAsVolume(
            secretName=k8s_secret_name,
        ),
    )
    volume_decrypted_secrets = ExtraVolume(name="user-secrets-volume", emptyDir=EmptyDir(medium="Memory"))

    decrypted_volume_mount = ExtraVolumeMount(
        name="user-secrets-volume",
        mountPath=secrets_mount_directory or project_constants.DEFAULT_SESSION_SECRETS_MOUNT_DIR.as_posix(),
        readOnly=True,
    )

    init_container = InitContainer.model_validate(
        dict(
            name="init-user-secrets",
            image=config.user_secrets.image,
            env=[
                dict(name="DATA_SERVICE_URL", value=config.data_service_url),
                dict(name="RENKU_ACCESS_TOKEN", value=user.access_token or ""),
                dict(name="ENCRYPTED_SECRETS_MOUNT_PATH", value="/encrypted"),
                dict(name="DECRYPTED_SECRETS_MOUNT_PATH", value="/decrypted"),
            ],
            volumeMounts=[
                dict(
                    name=f"{k8s_secret_name}-volume",
                    mountPath="/encrypted",
                    readOnly=True,
                ),
                dict(
                    name="user-secrets-volume",
                    mountPath="/decrypted",
                    readOnly=False,
                ),
            ],
            resources={
                "requests": {
                    "cpu": "50m",
                    "memory": "50Mi",
                }
            },
        )
    )

    return SessionExtraResources(
        init_containers=[init_container],
        volumes=[volume_k8s_secrets, volume_decrypted_secrets],
        volume_mounts=[decrypted_volume_mount],
    )
