import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING

from kubernetes import client

from ...config import config
from .utils import get_certificates_volume_mounts

if TYPE_CHECKING:
    from renku_notebooks.api.classes.server import UserServer


def git_clone(server: "UserServer"):
    etc_cert_volume_mount = get_certificates_volume_mounts(
        custom_certs=False,
        etc_certs=True,
        read_only_etc_certs=True,
    )

    prefix = "GIT_CLONE_"
    env = [
        {
            "name": f"{prefix}WORKSPACE_MOUNT_PATH",
            "value": server.workspace_mount_path.absolute().as_posix(),
        },
        {
            "name": f"{prefix}MOUNT_PATH",
            "value": server.work_dir.absolute().as_posix(),
        },
        {
            "name": f"{prefix}LFS_AUTO_FETCH",
            "value": "1" if server.server_options.lfs_auto_fetch else "0",
        },
        {
            "name": f"{prefix}USER__USERNAME",
            "value": server.user.username,
        },
        {
            "name": f"{prefix}USER__RENKU_TOKEN",
            "value": str(server.user.access_token),
        },
        {"name": f"{prefix}IS_GIT_PROXY_ENABLED", "value": "0" if server.user.anonymous else "1"},
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
    if not server.user.anonymous:
        env += [
            {"name": f"{prefix}USER__EMAIL", "value": server.user.gitlab_user.email},
            {
                "name": f"{prefix}USER__FULL_NAME",
                "value": server.user.gitlab_user.name,
            },
        ]

    # Set up git repositories
    for idx, repo in enumerate(server.repositories):
        obj_env = f"{prefix}REPOSITORIES_{idx}_"
        env.append(
            {
                "name": obj_env,
                "value": json.dumps(asdict(repo)),
            }
        )

    # Set up git providers
    for idx, provider in enumerate(server.required_git_providers):
        obj_env = f"{prefix}GIT_PROVIDERS_{idx}_"
        data = dict(id=provider.id, access_token_url=provider.access_token_url)
        env.append(
            {
                "name": obj_env,
                "value": json.dumps(data),
            }
        )

    return [
        {
            "type": "application/json-patch+json",
            "patch": [
                {
                    "op": "add",
                    "path": "/statefulset/spec/template/spec/initContainers/-",
                    "value": {
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
                            "fsGroup": 100,
                            "runAsGroup": 100,
                            "runAsUser": 1000,
                            "runAsNonRoot": True,
                        },
                        "volumeMounts": [
                            {
                                "mountPath": server.workspace_mount_path.absolute().as_posix(),
                                "name": "workspace",
                            },
                            *etc_cert_volume_mount,
                        ],
                        "env": env,
                    },
                },
            ],
        }
    ]


def certificates():
    init_container = client.V1Container(
        name="init-certificates",
        image=config.sessions.ca_certs.image,
        volume_mounts=get_certificates_volume_mounts(
            etc_certs=True,
            custom_certs=True,
            read_only_etc_certs=False,
        ),
        resources={
            "requests": {
                "cpu": "50m",
                "memory": "50Mi",
            }
        },
    )
    volume_etc_certs = client.V1Volume(
        name="etc-ssl-certs", empty_dir=client.V1EmptyDirVolumeSource(medium="Memory")
    )
    volume_custom_certs = client.V1Volume(
        name="custom-ca-certs",
        projected=client.V1ProjectedVolumeSource(
            default_mode=440,
            sources=[
                {"secret": {"name": i.get("secret")}}
                for i in config.sessions.ca_certs.secrets
                if i is not None and i.get("secret") is not None
            ],
        ),
    )
    api_client = client.ApiClient()
    patches = [
        {
            "type": "application/json-patch+json",
            "patch": [
                {
                    "op": "add",
                    "path": "/statefulset/spec/template/spec/initContainers/-",
                    "value": api_client.sanitize_for_serialization(init_container),
                },
            ],
        },
        {
            "type": "application/json-patch+json",
            "patch": [
                {
                    "op": "add",
                    "path": "/statefulset/spec/template/spec/volumes/-",
                    "value": api_client.sanitize_for_serialization(volume_etc_certs),
                },
            ],
        },
        {
            "type": "application/json-patch+json",
            "patch": [
                {
                    "op": "add",
                    "path": "/statefulset/spec/template/spec/volumes/-",
                    "value": api_client.sanitize_for_serialization(volume_custom_certs),
                },
            ],
        },
    ]
    return patches


def download_image(server: "UserServer"):
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
