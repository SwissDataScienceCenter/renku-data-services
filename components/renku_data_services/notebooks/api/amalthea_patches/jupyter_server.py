from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List

from renku_notebooks.errors.user import OverriddenEnvironmentVariableError

if TYPE_CHECKING:
    from renku_notebooks.api.classes.server import UserServer


def env(server: "UserServer"):
    # amalthea always makes the jupyter server the first container in the statefulset
    patch_list = [
        {
            "op": "add",
            "path": "/statefulset/spec/template/spec/containers/0/env/-",
            "value": {
                "name": "GIT_AUTOSAVE",
                "value": "1" if server.autosave_allowed else "0",
            },
        },
        {
            "op": "add",
            "path": "/statefulset/spec/template/spec/containers/0/env/-",
            "value": {
                "name": "RENKU_USERNAME",
                "value": server._user.username,
            },
        },
        {
            "op": "add",
            "path": "/statefulset/spec/template/spec/containers/0/env/-",
            "value": {"name": "CI_COMMIT_SHA", "value": server.commit_sha},
        },
        {
            "op": "add",
            "path": "/statefulset/spec/template/spec/containers/0/env/-",
            "value": {
                "name": "NOTEBOOK_DIR",
                "value": server.image_workdir.rstrip("/")
                + f"/work/{server.gl_project.path}",
            },
        },
        {
            "op": "add",
            "path": "/statefulset/spec/template/spec/containers/0/env/-",
            # Note that inside the main container, the mount path is
            # relative to $HOME.
            "value": {
                "name": "MOUNT_PATH",
                "value": f"/work/{server.gl_project.path}",
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
            "value": {"name": "PROJECT_NAME", "value": server.project},
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
                raise OverriddenEnvironmentVariableError(
                    message=f"Cannot override environment variable '{key}'"
                )

            patch_list.append(
                {
                    "op": "add",
                    "path": "/statefulset/spec/template/spec/containers/0/env/-",
                    "value": {"name": key, "value": value},
                }
            )
    patches = [{"type": "application/json-patch+json", "patch": patch_list}]
    return patches


def args():
    patches = []
    patches.append(
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
    )
    return patches


def image_pull_secret(server: "UserServer"):
    patches = []
    if server.is_image_private:
        image_pull_secret_name = server.server_name + "-image-secret"
        patches.append(
            {
                "type": "application/json-patch+json",
                "patch": [
                    {
                        "op": "add",
                        "path": "/image_pull_secret",
                        "value": {
                            "apiVersion": "v1",
                            "data": {
                                ".dockerconfigjson": server._get_registry_secret()
                            },
                            "kind": "Secret",
                            "metadata": {
                                "name": image_pull_secret_name,
                                "namespace": server._k8s_client.preferred_namespace,
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


def disable_service_links():
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


def rstudio_env_variables(server: "UserServer") -> List[Dict[str, Any]]:
    """Makes sure environment variables propagate for R and Rstudio.
    Since we cannot be certain that R/Rstudio is or isn't used we inject this every time
    the user has custom environment variables. These will not break jupyterlab.
    See: https://rviews.rstudio.com/2017/04/19/r-for-enterprise-understanding-r-s-startup/"""
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
                                [
                                    f"{k}={v}"
                                    for k, v in server.environment_variables.items()
                                ]
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
                        "mountPath": mount_location.absolute().as_posix(),
                        "subPath": mount_location.name,
                        "readOnly": True,
                    },
                },
            ],
        }
    ]
