from flask import current_app
import gitlab
from kubernetes import client
from kubernetes.client.rest import ApiException
from kubernetes.client.models import V1DeleteOptions
import base64
import json
from urllib.parse import urlparse, urljoin


from ...util.check_image import (
    parse_image_name,
    get_docker_token,
    image_exists,
    get_image_workdir,
)
from ...util.kubernetes_ import (
    get_k8s_client,
    filter_resources_by_annotations,
    make_server_name,
)
from ...util.file_size import parse_file_size
from .user import RegisteredUser


class UserServer:
    """Represents a jupyter server session."""

    def __init__(
        self,
        user,
        namespace,
        project,
        branch,
        commit_sha,
        notebook,
        image,
        server_options,
    ):
        self._renku_annotation_prefix = "renku.io/"
        self._check_flask_config()
        self._user = user
        self._k8s_client, self._k8s_namespace = get_k8s_client()
        self._k8s_api_instance = client.CustomObjectsApi(client.ApiClient())
        self.safe_username = self._user.safe_username
        self.namespace = namespace
        self.project = project
        self.branch = branch
        self.commit_sha = commit_sha
        self.notebook = notebook
        self.image = image
        self.server_options = server_options
        self.using_default_image = self.image == current_app.config.get("DEFAULT_IMAGE")
        self.git_host = urlparse(current_app.config["GITLAB_URL"]).netloc
        self.verified_image = None
        self.is_image_private = None
        self.image_workdir = None
        try:
            self.gl_project = self._user.get_renku_project(
                f"{self.namespace}/{self.project}"
            )
        except Exception as err:
            current_app.logger.warning("Cannot find project because:", err)
            self.gl_project = None
        self.js = None

    def _check_flask_config(self):
        """Check the app config and ensure minimum required parameters are present."""
        if current_app.config.get("GITLAB_URL", None) is None:
            raise ValueError(
                "The gitlab URL is missing, it must be provided in "
                "an environment variable called GITLAB_URL"
            )
        if current_app.config.get("IMAGE_REGISTRY", None) is None:
            raise ValueError(
                "The url to the docker image registry is missing, it must be provided in "
                "an environment variable called IMAGE_REGISTRY"
            )

    @property
    def server_name(self):
        """Make the name that is used to identify a unique user session"""
        return make_server_name(
            self._user.safe_username,
            self.namespace,
            self.project,
            self.branch,
            self.commit_sha,
        )

    @property
    def autosave_allowed(self):
        allowed = False
        if self._user is not None and type(self._user) is RegisteredUser:
            # gather project permissions for the logged in user
            permissions = self.gl_project.attributes["permissions"].items()
            access_levels = [x[1].get("access_level", 0) for x in permissions if x[1]]
            access_levels_string = ", ".join(map(lambda lev: str(lev), access_levels))
            current_app.logger.debug(
                "access level for user {username} in "
                "{namespace}/{project} = {access_level}".format(
                    username=self._user.username,
                    namespace=self.namespace,
                    project=self.project,
                    access_level=access_levels_string,
                )
            )
            access_level = gitlab.GUEST_ACCESS
            if len(access_levels) > 0:
                access_level = max(access_levels)
            if access_level >= gitlab.DEVELOPER_ACCESS:
                allowed = True

        return allowed

    def _branch_exists(self):
        """Check if a specific branch exists in the user's gitlab
        project. The branch name is not required by the API and therefore
        passing None to this function will return True."""
        if self.branch is not None:
            try:
                self._user.get_renku_project(
                    f"{self.namespace}/{self.project}"
                ).branches.get(self.branch)
            except Exception:
                return False
            else:
                return True
        return True

    def _commit_sha_exists(self):
        """Check if a specific commit sha exists in the user's gitlab project"""
        try:
            self._user.get_renku_project(
                f"{self.namespace}/{self.project}"
            ).commits.get(self.commit_sha)
        except Exception:
            return False
        else:
            return True

    def _verify_image(self):
        """Set the notebook image if not specified in the request. If specific image
        is requested then confirm it exists and it can be accessed."""
        if self.gl_project is None:
            return
        image = self.image
        if image is None:
            parsed_image = {
                "hostname": current_app.config.get("IMAGE_REGISTRY"),
                "image": self.gl_project.path_with_namespace.lower(),
                "tag": self.commit_sha[:7],
            }
            commit_image = (
                f"{current_app.config.get('IMAGE_REGISTRY')}/"
                f"{self.gl_project.path_with_namespace.lower()}"
                f":{self.commit_sha[:7]}"
            )
        else:
            parsed_image = parse_image_name(image)
        # get token
        token, is_image_private = get_docker_token(**parsed_image, user=self._user)
        # check if images exist
        image_exists_result = image_exists(**parsed_image, token=token)
        # assign image
        if image_exists_result and image is None:
            # the image tied to the commit exists
            verified_image = commit_image
        elif not image_exists_result and image is None:
            # the image tied to the commit does not exist, fallback to default image
            verified_image = current_app.config.get("DEFAULT_IMAGE")
            is_image_private = False
            current_app.logger.warn(
                f"Image for the selected commit {self.commit_sha} of {self.project}"
                " not found, using default image "
                f"{current_app.config.get('DEFAULT_IMAGE')}"
            )
        elif image_exists_result and image is not None:
            # a specific image was requested and it exists
            verified_image = image
        else:
            # a specific image was requested and it does not exist or any other case
            verified_image = None
            is_image_private = None
        self.using_default_image = verified_image == current_app.config["DEFAULT_IMAGE"]
        self.verified_image = verified_image
        self.is_image_private = is_image_private
        image_workdir = get_image_workdir(**parsed_image, token=token)
        self.image_workdir = (
            image_workdir
            if image_workdir is not None
            else current_app.config["IMAGE_DEFAULT_WORKDIR"]
        )

    def _get_registry_secret(self, b64encode=True):
        """If an image from gitlab is used and the image is not public
        create an image pull secret in k8s so that the private image can be used."""
        payload = {
            "auths": {
                current_app.config.get("IMAGE_REGISTRY"): {
                    "Username": "oauth2",
                    "Password": self._user.git_token,
                    "Email": self._user.gitlab_user.email,
                }
            }
        }
        output = json.dumps(payload)
        if b64encode:
            return base64.b64encode(output.encode()).decode()
        return output

    def _get_session_k8s_resources(self):
        cpu = float(self.server_options["cpu_request"])
        mem = self.server_options["mem_request"]
        gpu_req = self.server_options.get("gpu_request", {})
        gpu = {"nvidia.com/gpu": str(gpu_req)} if gpu_req else None
        resources = {
            "requests": {"memory": mem, "cpu": cpu},
            "limits": {"memory": mem},  # cpu is not limited
        }
        if gpu:
            resources["requests"] = {**resources["requests"], **gpu}
            resources["limits"] = {**resources["limits"], **gpu}
        if "ephemeral-storage" in self.server_options.keys():
            ephemeral_storage = (
                str(
                    round(
                        (
                            parse_file_size(self.server_options["ephemeral-storage"])
                            + 0
                            if current_app.config["NOTEBOOKS_SESSION_PVS_ENABLED"]
                            else parse_file_size(self.server_options["disk_request"])
                        )
                        / 1.074e9  # bytes to gibibytes
                    )
                )
                + "Gi"
            )
            resources["requests"] = {
                **resources["requests"],
                "ephemeral-storage": ephemeral_storage,
            }
            resources["limits"] = {
                **resources["limits"],
                "ephemeral-storage": ephemeral_storage,
            }
        return resources

    def _get_test_patches(self):
        """RFC 6901 patches support test statements that will cause the whole patch
        to fail if the test statements are not correct. This is used to ensure that the
        order of containers in the amalthea manifests is what the notebook service expects."""
        patches = []
        container_names = (
            current_app.config["AMALTHEA_CONTAINER_ORDER_REGISTERED_SESSION"]
            if type(self._user) is RegisteredUser
            else current_app.config["AMALTHEA_CONTAINER_ORDER_ANONYMOUS_SESSION"]
        )
        for container_ind, container_name in enumerate(container_names):
            patches.append(
                {
                    "type": "application/json-patch+json",
                    "patch": [
                        {
                            "op": "test",
                            "path": (
                                "/statefulset/spec/template/spec"
                                f"/containers/{container_ind}/name"
                            ),
                            "value": container_name,
                        }
                    ],
                }
            )
        return patches

    def _get_session_manifest(self):
        """Compose the body of the user session for the k8s operator"""
        patches = self._get_test_patches()
        # Add labels and annotations - applied to overall manifest and secret only
        labels = {
            "app": "jupyter",
            "component": "singleuser-server",
            f"{current_app.config['RENKU_ANNOTATION_PREFIX']}commit-sha": self.commit_sha,
            f"{current_app.config['RENKU_ANNOTATION_PREFIX']}gitlabProjectId": str(
                self.gl_project.id
            ),
            current_app.config["RENKU_ANNOTATION_PREFIX"]
            + "safe-username": self._user.safe_username,
        }
        annotations = {
            f"{current_app.config['RENKU_ANNOTATION_PREFIX']}commit-sha": self.commit_sha,
            f"{current_app.config['RENKU_ANNOTATION_PREFIX']}gitlabProjectId": str(
                self.gl_project.id
            ),
            current_app.config["RENKU_ANNOTATION_PREFIX"]
            + "safe-username": self._user.safe_username,
            f"{current_app.config['RENKU_ANNOTATION_PREFIX']}username": self._user.username,
            f"{current_app.config['RENKU_ANNOTATION_PREFIX']}servername": self.server_name,
            f"{current_app.config['RENKU_ANNOTATION_PREFIX']}branch": self.branch,
            f"{current_app.config['RENKU_ANNOTATION_PREFIX']}git-host": self.git_host,
            f"{current_app.config['RENKU_ANNOTATION_PREFIX']}namespace": self.gl_project.namespace[
                "full_path"
            ],
            current_app.config["RENKU_ANNOTATION_PREFIX"]
            + "projectName": self.gl_project.path.lower(),
            f"{current_app.config['RENKU_ANNOTATION_PREFIX']}requested-image": self.image,
        }
        # Add image pull secret if image is private
        if self.is_image_private:
            image_pull_secret_name = self.server_name + "-image-secret"
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
                                    ".dockerconfigjson": self._get_registry_secret()
                                },
                                "kind": "Secret",
                                "metadata": {
                                    "name": image_pull_secret_name,
                                    "namespace": self._k8s_namespace,
                                    "labels": labels,
                                    "annotations": annotations,
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
        # Add git init / sidecar container
        patches.append(
            {
                "type": "application/json-patch+json",
                "patch": [
                    {
                        "op": "add",
                        "path": "/statefulset/spec/template/spec/initContainers/-",
                        "value": {
                            "image": current_app.config["GIT_CLONE_IMAGE"],
                            "name": "git-clone",
                            "resources": {},
                            "securityContext": {
                                "allowPrivilegeEscalation": False,
                                "fsGroup": 100,
                                "runAsGroup": 100,
                                "runAsUser": 1000,
                            },
                            "workingDir": "/",
                            "volumeMounts": [
                                {
                                    "mountPath": "/work",
                                    "name": "workspace",
                                }
                            ],
                            "env": [
                                {
                                    "name": "MOUNT_PATH",
                                    "value": f"/work/{self.gl_project.path}",
                                },
                                {
                                    "name": "REPOSITORY_URL",
                                    "value": self.gl_project.http_url_to_repo,
                                },
                                {
                                    "name": "LFS_AUTO_FETCH",
                                    "value": "1"
                                    if self.server_options["lfs_auto_fetch"]
                                    else "0",
                                },
                                {"name": "COMMIT_SHA", "value": self.commit_sha},
                                {"name": "BRANCH", "value": self.branch},
                                {
                                    # used only for naming autosave branch
                                    "name": "RENKU_USERNAME",
                                    "value": self._user.username,
                                },
                                {
                                    "name": "GIT_AUTOSAVE",
                                    "value": "1" if self.autosave_allowed else "0",
                                },
                                {
                                    "name": "GIT_URL",
                                    "value": self._user.gitlab_client._base_url,
                                },
                                {
                                    "name": "GITLAB_OAUTH_TOKEN",
                                    "value": self._user.git_token,
                                },
                            ],
                        },
                    }
                ],
            }
        )
        # patches.append(
        #     {
        #         "type": "application/json-patch+json",
        #         "patch": [
        #             {
        #                 "op": "add",
        #                 "path": "/statefulset/spec/template/spec/containers/-",
        #                 "value": {
        #                     "image": current_app.config["GIT_RPC_SERVER_IMAGE"],
        #                     "name": "git-sidecar",
        #                     # Do not expose this until access control is in place
        #                     # "ports": [
        #                     #     {
        #                     #         "containerPort": 4000,
        #                     #         "name": "git-port",
        #                     #         "protocol": "TCP",
        #                     #     }
        #                     # ],
        #                     "env": [
        #                         {
        #                             "name": "MOUNT_PATH",
        #                             "value": f"/work/{self.gl_project.path}",
        #                         }
        #                     ],
        #                     "resources": {},
        #                     "securityContext": {
        #                         "allowPrivilegeEscalation": False,
        #                         "fsGroup": 100,
        #                         "runAsGroup": 100,
        #                         "runAsUser": 1000,
        #                     },
        #                     "volumeMounts": [
        #                         {
        #                             "mountPath": f"/work/{self.gl_project.path}/",
        #                             "name": "workspace",
        #                             "subPath": f"{self.gl_project.path}/",
        #                         }
        #                     ],
        #                     # Enable readiness and liveness only when control is in place
        #                     # "livenessProbe": {
        #                     #     "httpGet": {"port": 4000, "path": "/"},
        #                     #     "periodSeconds": 30,
        #                     #     # delay should equal periodSeconds x failureThreshold
        #                     #     # from readiness probe values
        #                     #     "initialDelaySeconds": 600,
        #                     # },
        #                     # the readiness probe will retry 36 times over 360 seconds to see
        #                     # if the pod is ready to accept traffic - this gives the user session
        #                     # a maximum of 360 seconds to setup the git sidecar and clone the repo
        #                     # "readinessProbe": {
        #                     #     "httpGet": {"port": 4000, "path": "/"},
        #                     #     "periodSeconds": 10,
        #                     #     "failureThreshold": 60,
        #                     # },
        #                 },
        #             }
        #         ],
        #     }
        # )
        # Add git proxy container
        patches.append(
            {
                "type": "application/json-patch+json",
                "patch": [
                    {
                        "op": "add",
                        "path": "/statefulset/spec/template/spec/containers/-",
                        "value": {
                            "image": current_app.config["GIT_HTTPS_PROXY_IMAGE"],
                            "name": "git-proxy",
                            "env": [
                                {
                                    "name": "REPOSITORY_URL",
                                    "value": self.gl_project.http_url_to_repo,
                                },
                                {"name": "MITM_PROXY_PORT", "value": "8080"},
                                {"name": "HEALTH_PORT", "value": "8081"},
                                {
                                    "name": "GITLAB_OAUTH_TOKEN",
                                    "value": self._user.git_token,
                                },
                                {
                                    "name": "ANONYMOUS_SESSION",
                                    "value": (
                                        "false"
                                        if type(self._user) is RegisteredUser
                                        else "true"
                                    ),
                                },
                            ],
                            "livenessProbe": {
                                "httpGet": {"path": "/health", "port": 8081},
                                "initialDelaySeconds": 3,
                            },
                            "readinessProbe": {
                                "httpGet": {"path": "/health", "port": 8081},
                                "initialDelaySeconds": 3,
                            },
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
                        "path": "/statefulset/spec/template/spec/volumes/-",
                        "value": {
                            "name": "notebook-helper-scripts-volume",
                            "configMap": {
                                "name": "notebook-helper-scripts",
                                "defaultMode": 493,
                            },
                        },
                    }
                ],
            }
        )
        # We can add this to expose the git side-car once it's protected.
        # patches.append(
        #     {
        #         "type": "application/json-patch+json",
        #         "patch": [
        #             {
        #                 "op": "add",
        #                 "path": "/service/spec/ports/-",
        #                 "value": {
        #                     "name": "git-service",
        #                     "port": 4000,
        #                     "protocol": "TCP",
        #                     "targetPort": 4000,
        #                 },
        #             }
        #         ],
        #     }
        # )
        patches.append(
            {
                "type": "application/json-patch+json",
                "patch": [
                    {
                        "op": "add",
                        "path": "/statefulset/spec/template/spec/tolerations",
                        "value": current_app.config["SESSION_TOLERATIONS"],
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
                        "path": "/statefulset/spec/template/spec/affinity",
                        "value": current_app.config["SESSION_AFFINITY"],
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
                        "path": "/statefulset/spec/template/spec/nodeSelector",
                        "value": current_app.config["SESSION_NODE_SELECTOR"],
                    }
                ],
            }
        )
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
                            "value": "1" if self.autosave_allowed else "0",
                        },
                    },
                    {
                        "op": "add",
                        "path": "/statefulset/spec/template/spec/containers/0/env/-",
                        "value": {
                            "name": "RENKU_USERNAME",
                            "value": self._user.username,
                        },
                    },
                    {
                        "op": "add",
                        "path": "/statefulset/spec/template/spec/containers/0/env/-",
                        "value": {"name": "CI_COMMIT_SHA", "value": self.commit_sha},
                    },
                    {
                        "op": "add",
                        "path": "/statefulset/spec/template/spec/containers/0/env/-",
                        "value": {
                            "name": "NOTEBOOK_DIR",
                            "value": self.image_workdir.rstrip("/")
                            + f"/work/{self.gl_project.path}",
                        },
                    },
                    {
                        "op": "add",
                        "path": "/statefulset/spec/template/spec/containers/0/env/-",
                        # Note that inside the main container, the mount path is
                        # relative to $HOME.
                        "value": {
                            "name": "MOUNT_PATH",
                            "value": f"/work/{self.gl_project.path}",
                        },
                    },
                    {
                        "op": "add",
                        "path": "/statefulset/spec/template/spec/containers/0/env/-",
                        "value": {"name": "PROJECT_NAME", "value": self.project},
                    },
                    {
                        "op": "add",
                        "path": "/statefulset/spec/template/spec/containers/0/env/-",
                        "value": {"name": "GIT_CLONE_REPO", "value": "true"},
                    },
                ],
            }
        )
        patches.append(
            {
                "type": "application/json-patch+json",
                "patch": [
                    {
                        "op": "add",
                        "path": "/statefulset/spec/template/spec/containers/0/lifecycle",
                        "value": {
                            "preStop": {
                                "exec": {
                                    "command": [
                                        "/bin/sh",
                                        "-c",
                                        "/usr/local/bin/pre-stop.sh",
                                        "||",
                                        "true",
                                    ]
                                }
                            }
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
                        "path": "/statefulset/spec/template/spec/containers/0/volumeMounts/-",
                        "value": {
                            "mountPath": "/usr/local/bin/pre-stop.sh",
                            "name": "notebook-helper-scripts-volume",
                            "subPath": "pre-stop.sh",
                        },
                    }
                ],
            }
        )
        # patches.append(
        #     {
        #         "type": "application/json-patch+json",
        #         "patch": [
        #             {
        #                 "op": "add",
        #                 "path": "/statefulset/spec/template/spec/containers/0/command",
        #                 "value": ["bash", "-c"],
        #             }
        #         ],
        #     }
        # )
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
        if type(self._user) is RegisteredUser:
            # modify oauth2 proxy for dev purposes only
            patches.append(
                {
                    "type": "application/json-patch+json",
                    "patch": [
                        {
                            "op": "add",
                            "path": "/statefulset/spec/template/spec/containers/1/env/-",
                            "value": {
                                "name": "OAUTH2_PROXY_INSECURE_OIDC_ALLOW_UNVERIFIED_EMAIL",
                                "value": current_app.config[
                                    "OIDC_ALLOW_UNVERIFIED_EMAIL"
                                ],
                            },
                        },
                        {
                            "op": "add",
                            "path": "/statefulset/spec/template/spec/initContainers/0/env/-",
                            "value": {
                                "name": "GIT_EMAIL",
                                "value": self._user.gitlab_user.email,
                            },
                        },
                        {
                            "op": "add",
                            "path": "/statefulset/spec/template/spec/initContainers/0/env/-",
                            "value": {
                                "name": "GIT_FULL_NAME",
                                "value": self._user.gitlab_user.name,
                            },
                        },
                    ],
                }
            )
        patches.append(
            {
                "type": "application/json-patch+json",
                "patch": [
                    {
                        "op": "add",
                        # "~1" == "/" for rfc6902 json patches
                        "path": (
                            "/ingress/metadata/annotations/"
                            "nginx.ingress.kubernetes.io~1configuration-snippet"
                        ),
                        "value": (
                            'more_set_headers "Content-Security-Policy: '
                            "frame-ancestors 'self' "
                            f'{self.server_url}";'
                        ),
                    }
                ],
            }
        )
        if current_app.config["NOTEBOOKS_SESSION_PVS_ENABLED"]:
            storage = {
                "size": self.server_options["disk_request"],
                "pvc": {
                    "enabled": True,
                    "storageClassName": current_app.config[
                        "NOTEBOOKS_SESSION_PVS_STORAGE_CLASS"
                    ],
                    "mountPath": self.image_workdir.rstrip("/") + "/work",
                },
            }
        else:
            storage = {
                "size": self.server_options["disk_request"]
                if current_app.config["USE_EMPTY_DIR_SIZE_LIMIT"]
                else "",
                "pvc": {
                    "enabled": False,
                    "mountPath": self.image_workdir.rstrip("/") + "/work",
                },
            }
        if type(self._user) is RegisteredUser:
            session_auth = {
                "token": "",
                "oidc": {
                    "enabled": True,
                    "clientId": current_app.config["OIDC_CLIENT_ID"],
                    "clientSecret": {"value": current_app.config["OIDC_CLIENT_SECRET"]},
                    "issuerUrl": self._user.oidc_issuer,
                    "authorizedEmails": [
                        self._user.email,
                    ],
                },
            }
        else:
            session_auth = {
                "token": self._user.username,
                "oidc": {"enabled": False},
            }
        manifest = {
            "apiVersion": f"{current_app.config['CRD_GROUP']}/{current_app.config['CRD_VERSION']}",
            "kind": "JupyterServer",
            "metadata": {
                "name": self.server_name,
                "labels": labels,
                "annotations": annotations,
            },
            "spec": {
                "auth": session_auth,
                "culling": {
                    "idleSecondsThreshold": (
                        current_app.config[
                            "CULLING_REGISTERED_IDLE_SESSIONS_THRESHOLD_SECONDS"
                        ]
                        if type(self._user) is RegisteredUser
                        else current_app.config[
                            "CULLING_ANONYMOUS_IDLE_SESSIONS_THRESHOLD_SECONDS"
                        ]
                    )
                },
                "jupyterServer": {
                    "defaultUrl": self.server_options["defaultUrl"],
                    "image": self.verified_image,
                    "rootDir": self.image_workdir.rstrip("/")
                    + f"/work/{self.gl_project.path}/",
                    "resources": self._get_session_k8s_resources(),
                },
                "routing": {
                    "host": urlparse(self.server_url).netloc,
                    "path": urlparse(self.server_url).path,
                    "ingressAnnotations": current_app.config[
                        "SESSION_INGRESS_ANNOTATIONS"
                    ],
                    "tls": {
                        "enabled": True,
                        "secretName": current_app.config["SESSION_TLS_SECRET"],
                    },
                },
                "storage": storage,
                "patches": patches,
            },
        }
        return manifest

    def start(self):
        """Create the jupyterserver resource in k8s."""
        error = []
        js = None
        if self.gl_project is None:
            error.append(f"project {self.project} does not exist")
        if not self._branch_exists():
            error.append(f"branch {self.branch} does not exist")
        if not self._commit_sha_exists():
            error.append(f"commit {self.commit_sha} does not exist")
        self._verify_image()
        if self.verified_image is None:
            error.append(f"image {self.image} does not exist or cannot be accessed")
        if len(error) == 0:
            try:
                js = self._k8s_api_instance.create_namespaced_custom_object(
                    group=current_app.config["CRD_GROUP"],
                    version=current_app.config["CRD_VERSION"],
                    namespace=self._k8s_namespace,
                    plural=current_app.config["CRD_PLURAL"],
                    body=self._get_session_manifest(),
                )
            except ApiException as e:
                current_app.logger.debug(
                    f"Cannot start the session {self.server_name}, error: {e}"
                )
                error.append("session could not be started in the cluster")
            else:
                self.js = js
        error_msg = None if len(error) == 0 else ", ".join(error)
        return js, error_msg

    def server_exists(self):
        """Check if the user server exists (i.e. is an actual pod in k8s)."""
        return self.js is not None

    def get_js(self):
        """Get the js resource of the user jupyter user session from k8s."""
        jss = filter_resources_by_annotations(
            self._user.jss,
            {
                f"{current_app.config['RENKU_ANNOTATION_PREFIX']}servername": self.server_name
            },
        )
        if len(jss) == 0:
            self.js = None
            return None
        elif len(jss) == 1:
            self.js = jss[0]
            return jss[0]
        else:  # more than one pod was matched
            raise Exception(
                f"The user session matches {len(jss)} k8s jupyterserver resources, "
                "it should match only one."
            )

    def set_js(self, js):
        self.js = js

    def stop(self, forced=False):
        """Stop user's server with specific name"""
        try:
            status = self._k8s_api_instance.delete_namespaced_custom_object(
                group=current_app.config["CRD_GROUP"],
                version=current_app.config["CRD_VERSION"],
                namespace=self._k8s_namespace,
                plural=current_app.config["CRD_PLURAL"],
                name=self.server_name,
                grace_period_seconds=0 if forced else None,
                body=V1DeleteOptions(propagation_policy="Foreground"),
            )
        except ApiException as e:
            current_app.logger.warning(
                f"Cannot delete server: {self.server_name} for user: "
                f"{self._user.username}, error: {e}"
            )
            return None
        else:
            return status

    def get_logs(self, max_log_lines=0, container_name="jupyter-server"):
        """Get the logs of the k8s pod that runs the user server."""
        js = self.js
        if js is None:
            return None
        pod_name = js["status"]["mainPod"]["name"]
        if max_log_lines == 0:
            logs = self._k8s_client.read_namespaced_pod_log(
                pod_name, self._k8s_namespace, container=container_name
            )
        else:
            logs = self._k8s_client.read_namespaced_pod_log(
                pod_name,
                self._k8s_namespace,
                tail_lines=max_log_lines,
                container=container_name,
            )
        return logs

    @property
    def server_url(self):
        """The URL where a user can access their session."""
        if type(self._user) is RegisteredUser:
            return urljoin(
                "https://" + current_app.config["SESSION_HOST"],
                f"sessions/{self.server_name}",
            )
        else:
            return urljoin(
                "https://" + current_app.config["SESSION_HOST"],
                f"sessions/{self.server_name}?token={self._user.username}",
            )

    @classmethod
    def from_js(cls, user, js):
        """Create a Server instance from a k8s jupyterserver object."""
        server = cls(
            user,
            js["metadata"]["annotations"].get(
                current_app.config["RENKU_ANNOTATION_PREFIX"] + "namespace"
            ),
            js["metadata"]["annotations"].get(
                current_app.config["RENKU_ANNOTATION_PREFIX"] + "projectName"
            ),
            js["metadata"]["annotations"].get(
                current_app.config["RENKU_ANNOTATION_PREFIX"] + "branch"
            ),
            js["metadata"]["annotations"].get(
                current_app.config["RENKU_ANNOTATION_PREFIX"] + "commit-sha"
            ),
            None,
            js["metadata"]["annotations"].get(
                current_app.config["RENKU_ANNOTATION_PREFIX"] + "requested-image"
            ),
            cls._get_server_options_from_js(js),
        )
        server.set_js(js)
        return server

    @classmethod
    def from_server_name(cls, user, server_name):
        """Create a Server instance from a Jupyter server name."""
        jss = user.jss
        jss = filter_resources_by_annotations(
            jss,
            {f"{current_app.config['RENKU_ANNOTATION_PREFIX']}servername": server_name},
        )
        if len(jss) != 1:
            return None
        js = jss[0]
        return cls.from_js(user, js)

    @staticmethod
    def _get_server_options_from_js(js):
        server_options = {}
        # url
        server_options["defaultUrl"] = js["spec"]["jupyterServer"]["defaultUrl"]
        # disk
        server_options["disk_request"] = js["spec"]["storage"].get("size")
        # cpu, memory, gpu, ephemeral storage
        k8s_res_name_xref = {
            "memory": "mem_request",
            "nvidia.com/gpu": "gpu_request",
            "cpu": "cpu_request",
            "ephemeral-storage": "ephemeral-storage",
        }
        js_resources = js["spec"]["jupyterServer"]["resources"]["requests"]
        for k8s_res_name in k8s_res_name_xref.keys():
            if k8s_res_name in js_resources.keys():
                server_options[k8s_res_name_xref[k8s_res_name]] = js_resources[
                    k8s_res_name
                ]
        # adjust ephemeral storage properly based on whether persistent volumes are used
        if "ephemeral-storage" in server_options.keys():
            server_options["ephemeral-storage"] = (
                str(
                    round(
                        (
                            parse_file_size(server_options["ephemeral-storage"]) - 0
                            if current_app.config["NOTEBOOKS_SESSION_PVS_ENABLED"]
                            else parse_file_size(server_options["disk_request"])
                        )
                        / 1.074e9  # bytes to gibibytes
                    )
                )
                + "Gi"
            )
        # lfs auto fetch
        for patches in js["spec"]["patches"]:
            for patch in patches.get("patch", []):
                if (
                    patch.get("path")
                    == "statefulset/spec/template/spec/containers/0/env/-"
                    and patch.get("value", {}).get("name") == "GIT_AUTOSAVE"
                ):
                    server_options["lfs_auto_fetch"] = (
                        patch.get("value", {}).get("value") == "1"
                    )
        return {
            **current_app.config["SERVER_OPTIONS_DEFAULTS"],
            **server_options,
        }
