def env(server):
    patches = []
    # amalthea always makes the jupyter server the first container in the statefulset
    patches.append(
        {
            "type": "application/json-patch+json",
            "patch": [
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
                    "value": {"name": "PROJECT_NAME", "value": server.project},
                },
                {
                    "op": "add",
                    "path": "/statefulset/spec/template/spec/containers/0/env/-",
                    "value": {"name": "GIT_CLONE_REPO", "value": "true"},
                },
            ],
        }
    )
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


def image_pull_secret(server):
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
                                "namespace": server._k8s_namespace,
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
