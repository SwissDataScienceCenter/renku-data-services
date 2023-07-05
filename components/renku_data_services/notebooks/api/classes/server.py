import base64
import json
from functools import lru_cache
from itertools import chain
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse

import gitlab
from flask import current_app

from ..amalthea_patches import cloudstorage as cloudstorage_patches
from ..amalthea_patches import general as general_patches
from ..amalthea_patches import git_proxy as git_proxy_patches
from ..amalthea_patches import git_sidecar as git_sidecar_patches
from ..amalthea_patches import init_containers as init_containers_patches
from ..amalthea_patches import inject_certificates as inject_certificates_patches
from ..amalthea_patches import jupyter_server as jupyter_server_patches
from ..amalthea_patches import ssh as ssh_patches
from ...config import config
from ...errors.programming import ConfigurationError, DuplicateEnvironmentVariableError
from ...errors.user import MissingResourceError
from .k8s_client import K8sClient
from .cloud_storage import ICloudStorageRequest
from ..schemas.server_options import ServerOptions
from .user import RegisteredUser, User
from ...util.check_image import (
    get_docker_token,
    get_image_workdir,
    image_exists,
    parse_image_name,
)
from ...util.kubernetes_ import make_server_name


class UserServer:
    """Represents a jupyter server session."""

    def __init__(
        self,
        user: User,
        namespace: str,
        project: str,
        branch: str,
        commit_sha: str,
        notebook: Optional[str],  # TODO: Is this value actually needed?
        image: Optional[str],
        server_options: ServerOptions,
        environment_variables: Dict[str, str],
        cloudstorage: List[ICloudStorageRequest],
        k8s_client: K8sClient,
    ):
        self._check_flask_config()
        self._user = user
        self._k8s_client: K8sClient = k8s_client
        self.safe_username = self._user.safe_username  # type:ignore
        self.namespace = namespace
        self.project = project
        self.branch = branch
        self.commit_sha = commit_sha
        self.notebook = notebook
        self.image = image
        self.server_options = server_options
        self.environment_variables = environment_variables
        self.using_default_image: bool = self.image == config.sessions.default_image
        self.git_host = urlparse(config.git.url).netloc
        self.verified_image: Optional[str] = None
        self.is_image_private: Optional[bool] = None
        self.image_workdir: Optional[str] = None
        self.cloudstorage: Optional[List[ICloudStorageRequest]] = cloudstorage
        self.gl_project_name = f"{self.namespace}/{self.project}"

    def _check_flask_config(self):
        """Check the app config and ensure minimum required parameters are present."""
        if config.git.url is None:
            raise ConfigurationError(
                message="The gitlab URL is missing, it must be provided in "
                "an environment variable called GITLAB_URL"
            )
        if config.git.registry is None:
            raise ConfigurationError(
                message="The url to the docker image registry is missing, it must be provided in "
                "an environment variable called IMAGE_REGISTRY"
            )

    @property
    def gl_project(self):
        return self._user.get_renku_project(self.gl_project_name)

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
    @lru_cache(maxsize=8)
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
        if self.branch is not None and self.gl_project is not None:
            try:
                self.gl_project.branches.get(self.branch)
            except Exception as err:
                current_app.logger.warning(
                    f"Branch {self.branch} cannot be verified or does not exist. {err}"
                )
            else:
                return True
        return False

    def _commit_sha_exists(self):
        """Check if a specific commit sha exists in the user's gitlab project"""
        if self.commit_sha is not None and self.gl_project is not None:
            try:
                self.gl_project.commits.get(self.commit_sha)
            except Exception as err:
                current_app.logger.warning(
                    f"Commit {self.commit_sha} cannot be verified or does not exist. {err}"
                )
            else:
                return True
        return False

    def _verify_image(self):
        """Set the notebook image if not specified in the request. If specific image
        is requested then confirm it exists and it can be accessed."""
        if self.gl_project is None:
            return
        image = self.image
        if image is None:
            parsed_image = {
                "hostname": config.git.registry,
                "image": self.gl_project.path_with_namespace.lower(),
                "tag": self.commit_sha[:7],
            }
            commit_image = (
                f"{config.git.registry}/"
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
            verified_image = config.sessions.default_image
            is_image_private = False
            current_app.logger.warn(
                f"Image for the selected commit {self.commit_sha} of {self.project}"
                " not found, using default image "
                f"{config.sessions.default_image}"
            )
        elif image_exists_result and image is not None:
            # a specific image was requested and it exists
            verified_image = image
        else:
            # a specific image was requested and it does not exist or any other case
            verified_image = None
            is_image_private = None
        self.using_default_image = verified_image == config.sessions.default_image
        self.verified_image = verified_image
        self.is_image_private = is_image_private
        image_workdir = get_image_workdir(**parsed_image, token=token)
        self.image_workdir = (
            image_workdir
            if image_workdir is not None
            else config.sessions.image_default_workdir
        )

    def _get_registry_secret(self, b64encode=True):
        """If an image from gitlab is used and the image is not public
        create an image pull secret in k8s so that the private image can be used."""
        payload = {
            "auths": {
                config.git.registry: {
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
        cpu_request = float(self.server_options.cpu)
        mem = self.server_options.memory
        gpu_req = self.server_options.gpu
        gpu = {"nvidia.com/gpu": str(gpu_req)} if gpu_req > 0 else None
        resources = {
            "requests": {"memory": mem, "cpu": cpu_request},
            "limits": {"memory": mem},
        }
        if config.sessions.enforce_cpu_limits == "lax":
            lax_cpu_limit_allowance_factor = 3
            resources["limits"]["cpu"] = lax_cpu_limit_allowance_factor * cpu_request
        elif config.sessions.enforce_cpu_limits == "strict":
            resources["limits"]["cpu"] = cpu_request
        if gpu:
            resources["requests"] = {**resources["requests"], **gpu}
            resources["limits"] = {**resources["limits"], **gpu}
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
                general_patches.priority_class(self),
                jupyter_server_patches.args(),
                jupyter_server_patches.env(self),
                jupyter_server_patches.image_pull_secret(self),
                jupyter_server_patches.disable_service_links(),
                jupyter_server_patches.rstudio_env_variables(self),
                git_proxy_patches.main(self),
                git_sidecar_patches.main(self),
                general_patches.oidc_unverified_email(self),
                cloudstorage_patches.main(self),
                ssh_patches.main(),
                # init container for certs must come before all other init containers
                # so that it runs first before all other init containers
                init_containers_patches.certificates(),
                init_containers_patches.download_image(self),
                init_containers_patches.git_clone(self),
                inject_certificates_patches.proxy(self),
            )
        )

        self._check_environment_variables_overrides(patches)

        # Storage
        if config.sessions.storage.pvs_enabled:
            storage = {
                "size": self.server_options.storage,
                "pvc": {
                    "enabled": True,
                    "storageClassName": config.sessions.storage.pvs_storage_class,
                    "mountPath": self.image_workdir.rstrip("/") + "/work",
                },
            }
        else:
            storage = {
                "size": self.server_options.storage
                if config.sessions.storage.use_empty_dir_size_limit
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
                    "clientId": config.sessions.oidc.client_id,
                    "clientSecret": {"value": config.sessions.oidc.client_secret},
                    "issuerUrl": self._user.oidc_issuer,
                    "authorizedEmails": [self._user.email],
                },
            }
        else:
            session_auth = {
                "token": self._user.username,
                "oidc": {"enabled": False},
            }
        # Combine everything into the manifest
        manifest = {
            "apiVersion": f"{config.amalthea.group}/{config.amalthea.version}",
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
                        config.sessions.culling.registered.idle_seconds
                        if type(self._user) is RegisteredUser
                        else config.sessions.culling.anonymous.idle_seconds
                    ),
                    "maxAgeSecondsThreshold": (
                        config.sessions.culling.registered.max_age_seconds
                        if type(self._user) is RegisteredUser
                        else config.sessions.culling.anonymous.max_age_seconds
                    ),
                },
                "jupyterServer": {
                    "defaultUrl": self.server_options.default_url,
                    "image": self.verified_image,
                    "rootDir": self.image_workdir.rstrip("/")
                    + f"/work/{self.gl_project.path}/",
                    "resources": self._get_session_k8s_resources(),
                },
                "routing": {
                    "host": urlparse(self.server_url).netloc,
                    "path": urlparse(self.server_url).path,
                    "ingressAnnotations": config.sessions.ingress.annotations,
                    "tls": {
                        "enabled": config.sessions.ingress.tls_secret is not None,
                        "secretName": config.sessions.ingress.tls_secret,
                    },
                },
                "storage": storage,
                "patches": patches,
            },
        }
        return manifest

    @staticmethod
    def _check_environment_variables_overrides(patches_list):
        """Check if any patch overrides server's environment variables with a different value,
        or if two patches create environment variables with different values."""
        env_vars = {}

        for patch_list in patches_list:
            patches = patch_list["patch"]

            for patch in patches:
                path = patch["path"].lower()
                if path.endswith("/env/-"):
                    name = patch["value"]["name"]
                    value = patch["value"]["value"]
                    key = (path, name)

                    if key in env_vars and env_vars[key] != value:
                        raise DuplicateEnvironmentVariableError(
                            message=f"Environment variable {path}::{name} is being overridden by "
                            "multiple patches"
                        )
                    else:
                        env_vars[key] = value

    def start(self) -> Optional[Dict[str, Any]]:
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
            js = self._k8s_client.create_server(
                self._get_session_manifest(), self.safe_username
            )
        else:
            raise MissingResourceError(
                message=(
                    "Cannot start the session because the following Git "
                    f"or Docker resources are missing: {', '.join(error)}"
                )
            )
        return js

    @property
    def server_url(self) -> str:
        """The URL where a user can access their session."""
        if type(self._user) is RegisteredUser:
            return urljoin(
                "https://" + config.sessions.ingress.host,
                f"sessions/{self.server_name}",
            )
        else:
            return urljoin(
                "https://" + config.sessions.ingress.host,
                f"sessions/{self.server_name}?token={self._user.username}",
            )

    def __str__(self):
        return (
            f"<UserServer user: {self._user.username} namespace: {self.namespace} "
            f"project: {self.project} commit: {self.commit_sha} image: {self.image}>"
        )

    def get_annotations(self):
        prefix = config.session_get_endpoint_annotations.renku_annotation_prefix
        annotations = {
            f"{prefix}commit-sha": self.commit_sha,
            f"{prefix}gitlabProjectId": None,
            f"{prefix}safe-username": self._user.safe_username,
            f"{prefix}username": self._user.username,
            f"{prefix}userId": self._user.id,
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
        prefix = config.session_get_endpoint_annotations.renku_annotation_prefix
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
