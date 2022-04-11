from flask import current_app
import gitlab
from itertools import chain
from kubernetes import client
from kubernetes.client.exceptions import ApiException
from kubernetes.client.models import V1DeleteOptions
import base64
import json
from urllib.parse import urlparse, urljoin


from ..amalthea_patches import (
    general as general_patches,
    git_proxy as git_proxy_patches,
    git_sidecar as git_sidecar_patches,
    init_containers as init_containers_patches,
    inject_certificates as inject_certificates_patches,
    jupyter_server as jupyter_server_patches,
    cloudstorage as cloudstorage_patches,
)
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
from .s3mount import S3mount


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
        cloudstorage,
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
        self.cloudstorage = cloudstorage
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
        prefix = current_app.config["RENKU_ANNOTATION_PREFIX"]
        if self.js is not None:
            try:
                return self.js["metadata"]["annotations"][f"{prefix}servername"]
            except KeyError:
                pass  # make server name from params - required fields missing from k8s resource
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
        cpu_request = float(self.server_options["cpu_request"])
        mem = self.server_options["mem_request"]
        gpu_req = self.server_options.get("gpu_request", {})
        gpu = {"nvidia.com/gpu": str(gpu_req)} if gpu_req else None
        resources = {
            "requests": {"memory": mem, "cpu": cpu_request},
            "limits": {"memory": mem},
        }
        if current_app.config["ENFORCE_CPU_LIMITS"] == "lax":
            if "cpu_request" in current_app.config["SERVER_OPTIONS_UI"]:
                resources["limits"]["cpu"] = max(
                    current_app.config["SERVER_OPTIONS_UI"]["cpu_request"]["options"]
                )
            else:
                resources["limits"]["cpu"] = cpu_request
        elif current_app.config["ENFORCE_CPU_LIMITS"] == "strict":
            resources["limits"]["cpu"] = cpu_request
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

    def _get_session_manifest(self):
        """Compose the body of the user session for the k8s operator"""
        patches = list(
            chain(
                general_patches.test(self),
                general_patches.session_tolerations(),
                general_patches.session_affinity(),
                general_patches.session_node_selector(),
                general_patches.termination_grace_period(),
                jupyter_server_patches.args(),
                jupyter_server_patches.env(self),
                jupyter_server_patches.image_pull_secret(self),
                jupyter_server_patches.disable_service_links(),
                git_proxy_patches.main(self),
                git_sidecar_patches.main(self),
                general_patches.oidc_unverified_email(self),
                cloudstorage_patches.main(self),
                # init container for certs must come before all other init containers
                # so that it runs first before all other init containers
                init_containers_patches.certificates(),
                init_containers_patches.git_clone(self),
                inject_certificates_patches.proxy(self),
            )
        )
        # Storage
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
        # Authentication
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
        # Combine everything into the manifest
        manifest = {
            "apiVersion": f"{current_app.config['CRD_GROUP']}/{current_app.config['CRD_VERSION']}",
            "kind": "JupyterServer",
            "metadata": {
                "name": self.server_name,
                "labels": self.get_labels(),
                "annotations": self.get_annotations(),
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
                    ),
                    "maxAgeSecondsThreshold": (
                        current_app.config[
                            "CULLING_REGISTERED_MAX_AGE_THRESHOLD_SECONDS"
                        ]
                        if type(self._user) is RegisteredUser
                        else current_app.config[
                            "CULLING_ANONYMOUS_MAX_AGE_THRESHOLD_SECONDS"
                        ]
                    ),
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

    def get_logs(self, max_log_lines=0):
        """Get the logs of all containers in the server pod."""
        js = self.js
        if js is None:
            return None
        output = {}
        pod_name = js["status"]["mainPod"]["name"]
        all_containers = js["status"]["mainPod"]["status"].get(
            "containerStatuses", []
        ) + js["status"]["mainPod"]["status"].get("initContainerStatuses", [])
        for container in all_containers:
            container_name = container["name"]
            try:
                logs = self._k8s_client.read_namespaced_pod_log(
                    pod_name,
                    self._k8s_namespace,
                    container=container_name,
                    tail_lines=max_log_lines if max_log_lines > 0 else None,
                    timestamps=True,
                )
            except ApiException as err:
                if err.status in [400, 404]:
                    continue  # container does not exist or is not ready yet
                else:
                    raise
            else:
                output[container_name] = logs

        if len(output.keys()) == 0:
            return None
        else:
            return output

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
            js["spec"]["jupyterServer"]["image"],
            cls._get_server_options_from_js(js),
            S3mount.s3mounts_from_js(js),
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

    def __str__(self):
        return (
            f"<UserServer user: {self._user.username} namespace: {self.namespace} "
            f"project: {self.project} commit: {self.commit_sha} image: {self.image}>"
        )

    def get_annotations(self):
        prefix = current_app.config["RENKU_ANNOTATION_PREFIX"]
        annotations = {
            f"{prefix}commit-sha": self.commit_sha,
            f"{prefix}gitlabProjectId": None,
            f"{prefix}safe-username": self._user.safe_username,
            f"{prefix}username": self._user.username,
            f"{prefix}servername": self.server_name,
            f"{prefix}branch": self.branch,
            f"{prefix}git-host": self.git_host,
            f"{prefix}namespace": self.namespace,
            f"{prefix}projectName": self.project,
            f"{prefix}requested-image": self.image,
            f"{prefix}repository": None,
        }
        if self.gl_project is not None:
            annotations[f"{prefix}gitlabProjectId"] = str(self.gl_project.id)
            annotations[f"{prefix}repository"] = self.gl_project.web_url
        return annotations

    def get_labels(self):
        prefix = current_app.config["RENKU_ANNOTATION_PREFIX"]
        labels = {
            "app": "jupyter",
            "component": "singleuser-server",
            f"{prefix}commit-sha": self.commit_sha,
            f"{prefix}gitlabProjectId": None,
            f"{prefix}safe-username": self._user.safe_username,
        }
        if self.gl_project is not None:
            labels[f"{prefix}gitlabProjectId"] = str(self.gl_project.id)
        return labels
