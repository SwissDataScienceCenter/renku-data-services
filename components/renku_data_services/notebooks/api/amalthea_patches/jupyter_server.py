"""Patches to modify the jupyter container in the session."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from kubernetes import client

from renku_data_services.base_models.core import AuthenticatedAPIUser
from renku_data_services.notebooks.errors.user import OverriddenEnvironmentVariableError

if TYPE_CHECKING:
    # NOTE: If these are directly imported then you get circular imports.
    from renku_data_services.notebooks.api.classes.server import UserServer


def env(server: UserServer) -> list[dict[str, Any]]:
    """Injects environment variables in the jupyter container in the session.

    Amalthea always makes the jupyter server the first container in the statefulset
    """

    commit_sha = getattr(server, "commit_sha", None)
    project = getattr(server, "project", None)

    patch_list: list[dict[str, Any]] = [
        {
            "op": "add",
            "path": "/statefulset/spec/template/spec/containers/0/env/-",
            "value": {
                "name": "RENKU_USERNAME",
                "value": server.user.id,
            },
        },
        {
            "op": "add",
            "path": "/statefulset/spec/template/spec/containers/0/env/-",
            "value": {"name": "CI_COMMIT_SHA", "value": commit_sha},
        },
        {
            "op": "add",
            "path": "/statefulset/spec/template/spec/containers/0/env/-",
            "value": {
                "name": "NOTEBOOK_DIR",
                "value": server.work_dir.as_posix(),
            },
        },
        {
            "op": "add",
            "path": "/statefulset/spec/template/spec/containers/0/env/-",
            # Note that inside the main container, the mount path is
            # relative to $HOME.
            "value": {
                "name": "MOUNT_PATH",
                "value": server.work_dir.as_posix(),
            },
        },
        {
            "op": "add",
            "path": "/statefulset/spec/template/spec/containers/0/env/-",
            "value": {"name": "SESSION_URL", "value": server.server_url},
        },
        {
            "op": "add",
            "path": "/statefulset/spec/template/spec/containers/0/env/-",
            "value": {"name": "PROJECT_NAME", "value": project},
        },
        {
            "op": "add",
            "path": "/statefulset/spec/template/spec/containers/0/env/-",
            "value": {"name": "GIT_CLONE_REPO", "value": "true"},
        },
    ]

    env_vars = {p["value"]["name"]: p["value"]["value"] for p in patch_list}

    if server.environment_variables:
        for key, value in server.environment_variables.items():
            if key in env_vars and value != env_vars[key]:
                raise OverriddenEnvironmentVariableError(message=f"Cannot override environment variable '{key}'")

            patch_list.append(
                {
                    "op": "add",
                    "path": "/statefulset/spec/template/spec/containers/0/env/-",
                    "value": {"name": key, "value": value},
                }
            )
    patches = [{"type": "application/json-patch+json", "patch": patch_list}]
    return patches


def args() -> list[dict[str, Any]]:
    """Sets the arguments for running the jupyter container."""
    patches = [
        {
            "type": "application/json-patch+json",
            "patch": [
                {
                    "op": "add",
                    "path": "/statefulset/spec/template/spec/containers/0/args",
                    "value": ["jupyter", "notebook"],
                }
            ],
        }
    ]
    return patches


def image_pull_secret(server: UserServer, access_token: str | None) -> list[dict[str, Any]]:
    """Adds an image pull secret to the session if the session image is not public."""
    patches = []
    if isinstance(server.user, AuthenticatedAPIUser) and server.is_image_private and access_token:
        image_pull_secret_name = server.server_name + "-image-secret"
        registry_secret = {
            "auths": {
                server.config.git.registry: {
                    "Username": "oauth2",
                    "Password": access_token,
                    "Email": server.user.email,
                }
            }
        }
        registry_secret = json.dumps(registry_secret)
        registry_secret = base64.b64encode(registry_secret.encode()).decode()
        patches.append(
            {
                "type": "application/json-patch+json",
                "patch": [
                    {
                        "op": "add",
                        "path": "/image_pull_secret",
                        "value": {
                            "apiVersion": "v1",
                            "data": {".dockerconfigjson": registry_secret},
                            "kind": "Secret",
                            "metadata": {
                                "name": image_pull_secret_name,
                                "namespace": server.k8s_namespace(),
                            },
                            "type": "kubernetes.io/dockerconfigjson",
                        },
                    }
                ],
            }
        )
        patches.append(
            {
                "type": "application/json-patch+json",
                "patch": [
                    {
                        "op": "add",
                        "path": "/statefulset/spec/template/spec/imagePullSecrets/-",
                        "value": {"name": image_pull_secret_name},
                    }
                ],
            }
        )
    return patches


def disable_service_links() -> list[dict[str, Any]]:
    """Disables the addition of cluster-specific URLs or configs inside the session container as env variables."""
    return [
        {
            "type": "application/json-patch+json",
            "patch": [
                {
                    "op": "add",
                    "path": "/statefulset/spec/template/spec/enableServiceLinks",
                    "value": False,
                }
            ],
        }
    ]


def rstudio_env_variables(server: UserServer) -> list[dict[str, Any]]:
    """Makes sure environment variables propagate for R and Rstudio.

    Since we cannot be certain that R/Rstudio is or isn't used we inject this every time
    the user has custom environment variables. These will not break jupyterlab.
    See: https://rviews.rstudio.com/2017/04/19/r-for-enterprise-understanding-r-s-startup/
    """
    if not server.environment_variables:
        return []
    secret_name = f"{server.server_name}-renviron"
    mount_location = Path("/home/jovyan/.Renviron")
    return [
        {
            "type": "application/json-patch+json",
            "patch": [
                # INFO: Put the environment variables in a secret
                {
                    "op": "add",
                    "path": "/renviron",
                    "value": {
                        "apiVersion": "v1",
                        "kind": "Secret",
                        "metadata": {"name": secret_name},
                        "stringData": {
                            mount_location.name: "\n".join(
                                [f"{k}={v}" for k, v in server.environment_variables.items()]
                            )
                        },
                    },
                },
                # INFO: Mount the secret with environment variables in the session as a file
                {
                    "op": "add",
                    "path": "/statefulset/spec/template/spec/volumes/-",
                    "value": {
                        "name": secret_name,
                        "secret": {
                            "secretName": secret_name,
                        },
                    },
                },
                {
                    "op": "add",
                    "path": "/statefulset/spec/template/spec/containers/0/volumeMounts/-",
                    "value": {
                        "name": secret_name,
                        "mountPath": mount_location.as_posix(),
                        "subPath": mount_location.name,
                        "readOnly": True,
                    },
                },
            ],
        }
    ]


def user_secrets(server: UserServer) -> list[dict[str, Any]]:
    """Patches to add volumes and corresponding mount volumes to the main container for user-requested secrets."""

    if server.user_secrets is None:
        return []

    patch_list = []

    k8s_secret_name = server.user_secrets.name
    mount_path = server.user_secrets.mount_path

    volume_decrypted_secrets = client.V1Volume(
        name="user-secrets-volume", empty_dir=client.V1EmptyDirVolumeSource(medium="Memory")
    )
    volume_k8s_secret = client.V1Volume(
        name=f"{k8s_secret_name}-volume",
        secret=client.V1SecretVolumeSource(secret_name=k8s_secret_name),
    )

    init_container = client.V1Container(
        name="init-user-secrets",
        image=server.config.user_secrets.image,
        env=[
            client.V1EnvVar(name="DATA_SERVICE_URL", value=server.config.data_service_url),
            client.V1EnvVar(name="RENKU_ACCESS_TOKEN", value=str(server.user.access_token)),
            client.V1EnvVar(name="ENCRYPTED_SECRETS_MOUNT_PATH", value="/encrypted"),
            client.V1EnvVar(name="DECRYPTED_SECRETS_MOUNT_PATH", value="/decrypted"),
        ],
        volume_mounts=[
            client.V1VolumeMount(name=f"{k8s_secret_name}-volume", mount_path="/encrypted", read_only=True),
            client.V1VolumeMount(name="user-secrets-volume", mount_path="/decrypted", read_only=False),
        ],
        resources={
            "requests": {
                "cpu": "50m",
                "memory": "50Mi",
            }
        },
    )

    api_client = client.ApiClient()

    # Add init container
    patch_list.append(
        {
            "type": "application/json-patch+json",
            "patch": [
                {
                    "op": "add",
                    "path": "/statefulset/spec/template/spec/initContainers/-",
                    "value": api_client.sanitize_for_serialization(init_container),
                },
            ],
        }
    )

    # Create volumes for k8s secret and decrypted secrets
    patch_list.append(
        {
            "type": "application/json-patch+json",
            "patch": [
                {
                    "op": "add",
                    "path": "/statefulset/spec/template/spec/volumes/-",
                    "value": api_client.sanitize_for_serialization(volume_decrypted_secrets),
                },
                {
                    "op": "add",
                    "path": "/statefulset/spec/template/spec/volumes/-",
                    "value": api_client.sanitize_for_serialization(volume_k8s_secret),
                },
            ],
        }
    )

    # Add decrypted user secrets volume mount to main container
    decrypted_volume_mount = client.V1VolumeMount(name="user-secrets-volume", mount_path=mount_path, read_only=True)
    patch_list.append(
        {
            "type": "application/json-patch+json",
            "patch": [
                {
                    "op": "add",
                    "path": "/statefulset/spec/template/spec/containers/0/volumeMounts/-",
                    "value": api_client.sanitize_for_serialization(decrypted_volume_mount),
                },
            ],
        }
    )

    return patch_list
