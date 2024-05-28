from abc import ABC
from itertools import chain
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from flask import current_app

from ...config import config
from ...errors.programming import ConfigurationError, DuplicateEnvironmentVariableError
from ...errors.user import MissingResourceError
from ..amalthea_patches import cloudstorage as cloudstorage_patches
from ..amalthea_patches import general as general_patches
from ..amalthea_patches import git_proxy as git_proxy_patches
from ..amalthea_patches import git_sidecar as git_sidecar_patches
from ..amalthea_patches import init_containers as init_containers_patches
from ..amalthea_patches import inject_certificates as inject_certificates_patches
from ..amalthea_patches import jupyter_server as jupyter_server_patches
from ..amalthea_patches import ssh as ssh_patches
from ..schemas.secrets import K8sUserSecrets
from ..schemas.server_options import ServerOptions
from .cloud_storage import ICloudStorageRequest
from .k8s_client import K8sClient
from .repository import GitProvider, Repository
from .user import AnonymousUser, RegisteredUser


class UserServer(ABC):
    """Represents a Renku server session."""

    def __init__(
        self,
        user: AnonymousUser | RegisteredUser,
        server_name: str,
        image: str | None,
        server_options: ServerOptions,
        environment_variables: dict[str, str],
        user_secrets: K8sUserSecrets | None,
        cloudstorage: list[ICloudStorageRequest],
        k8s_client: K8sClient,
        workspace_mount_path: Path,
        work_dir: Path,
        using_default_image: bool = False,
        is_image_private: bool = False,
        repositories: list[Repository] = [],
        **_,
    ):
        self._check_flask_config()
        self._user = user
        self.server_name = server_name
        self._k8s_client: K8sClient = k8s_client
        self.safe_username = self._user.safe_username
        self.image = image
        self.server_options = server_options
        self.environment_variables = environment_variables
        self.user_secrets = user_secrets
        self.using_default_image = using_default_image
        self.workspace_mount_path = workspace_mount_path
        self.work_dir = work_dir
        self.cloudstorage: list[ICloudStorageRequest] | None = cloudstorage
        self.is_image_private = is_image_private

        if self.server_options.idle_threshold_seconds is not None:
            self.idle_seconds_threshold = self.server_options.idle_threshold_seconds
        else:
            self.idle_seconds_threshold: int = (
                config.sessions.culling.registered.idle_seconds
                if isinstance(self._user, RegisteredUser)
                else config.sessions.culling.anonymous.idle_seconds
            )

        if self.server_options.hibernation_threshold_seconds is not None:
            self.hibernated_seconds_threshold: int = self.server_options.hibernation_threshold_seconds
        else:
            self.hibernated_seconds_threshold: int = (
                config.sessions.culling.registered.hibernated_seconds
                if isinstance(user, RegisteredUser)
                else config.sessions.culling.anonymous.hibernated_seconds
            )
        self._repositories: list[Repository] = repositories
        self._git_providers: list[GitProvider] | None = None
        self._has_configured_git_providers = False

    @property
    def user(self) -> AnonymousUser | RegisteredUser:
        """Getter for server's user."""
        return self._user

    @property
    def k8s_client(self) -> K8sClient:
        """Return server's k8s client."""
        return self._k8s_client

    @property
    def repositories(self) -> list[Repository]:
        # Configure git repository providers based on matching URLs.
        if not self._has_configured_git_providers:
            for repo in self._repositories:
                found_provider = None
                for provider in self.git_providers:
                    if urlparse(provider.url).netloc == urlparse(repo.url).netloc:
                        found_provider = provider
                        break
                if found_provider is not None:
                    repo.provider = found_provider.id
            self._has_configured_git_providers = True

        return self._repositories

    @property
    def server_url(self) -> str:
        """The URL where a user can access their session."""
        if type(self._user) is RegisteredUser:
            return urljoin(
                f"https://{config.sessions.ingress.host}",
                f"sessions/{self.server_name}",
            )
        return urljoin(
            f"https://{config.sessions.ingress.host}",
            f"sessions/{self.server_name}?token={self._user.username}",
        )

    @property
    def git_providers(self) -> list[GitProvider]:
        """The list of git providers."""
        if self._git_providers is None:
            self._git_providers = config.git_provider_helper.get_providers(
                user=self.user
            )
        return self._git_providers

    @property
    def required_git_providers(self) -> list[GitProvider]:
        """The list of required git providers."""
        required_provider_ids: set[str] = set(
            r.provider for r in self.repositories if r.provider
        )
        return [p for p in self.git_providers if p.id in required_provider_ids]

    def __str__(self):
        return (
            f"<UserServer user: {self._user.username} server_name: {self.server_name}>"
        )

    def start(self) -> dict[str, Any] | None:
        """Create the jupyterserver resource in k8s."""
        errors = self._get_start_errors()
        if errors:
            raise MissingResourceError(
                message=(
                    "Cannot start the session because the following Git "
                    f"or Docker resources are missing: {', '.join(errors)}"
                )
            )
        return self._k8s_client.create_server(
            self._get_session_manifest(), self.safe_username
        )

    @staticmethod
    def _check_flask_config():
        """Check the app config and ensure minimum required parameters are present."""
        if config.git.url is None:
            raise ConfigurationError(
                message="The gitlab URL is missing, it must be provided in an environment variable called GITLAB_URL"
            )
        if config.git.registry is None:
            raise ConfigurationError(
                message="The url to the docker image registry is missing, it must be provided in "
                "an environment variable called IMAGE_REGISTRY"
            )

    @staticmethod
    def _check_environment_variables_overrides(patches_list: list[dict[str, Any]]):
        """Check if any patch overrides server's environment variables.

        Checks if it overrides with a different value or if two patches create environment variables with different
        values.
        """
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

    def _get_start_errors(self) -> list[str]:
        """Check if there are any errors before starting the server."""
        errors: list[str]
        errors = []
        if self.image is None:
            errors.append(f"image {self.image} does not exist or cannot be accessed")
        return errors

    def _get_session_manifest(self):
        """Compose the body of the user session for the k8s operator."""
        patches = self._get_patches()
        self._check_environment_variables_overrides(patches)

        # Storage
        if config.sessions.storage.pvs_enabled:
            storage = {
                "size": self.server_options.storage,
                "pvc": {
                    "enabled": True,
                    "storageClassName": config.sessions.storage.pvs_storage_class,
                    "mountPath": self.workspace_mount_path.absolute().as_posix(),
                },
            }
        else:
            storage = {
                "size": (self.server_options.storage if config.sessions.storage.use_empty_dir_size_limit else ""),
                "pvc": {
                    "enabled": False,
                    "mountPath": self.workspace_mount_path.absolute().as_posix(),
                },
            }
        # Authentication
        if isinstance(self._user, RegisteredUser):
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
                    "idleSecondsThreshold": self.idle_seconds_threshold,
                    "maxAgeSecondsThreshold": (
                        config.sessions.culling.registered.max_age_seconds
                        if isinstance(self._user, RegisteredUser)
                        else config.sessions.culling.anonymous.max_age_seconds
                    ),
                    "hibernatedSecondsThreshold": self.hibernated_seconds_threshold,
                },
                "jupyterServer": {
                    "defaultUrl": self.server_options.default_url,
                    "image": self.image,
                    "rootDir": self.work_dir.absolute().as_posix(),
                    "resources": self.server_options.to_k8s_resources(
                        enforce_cpu_limits=config.sessions.enforce_cpu_limits
                    ),
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
    def _get_renku_annotation_prefix() -> str:
        return config.session_get_endpoint_annotations.renku_annotation_prefix

    def _get_patches(self) -> list[dict[str, Any]]:
        return list(
            chain(
                general_patches.test(self),
                general_patches.session_tolerations(self),
                general_patches.session_affinity(self),
                general_patches.session_node_selector(self),
                general_patches.priority_class(self),
                general_patches.dev_shm(self),
                jupyter_server_patches.args(),
                jupyter_server_patches.env(self),
                jupyter_server_patches.image_pull_secret(self),
                jupyter_server_patches.disable_service_links(),
                jupyter_server_patches.rstudio_env_variables(self),
                jupyter_server_patches.user_secrets(self),
                git_proxy_patches.main(self),
                git_sidecar_patches.main(self),
                general_patches.oidc_unverified_email(self),
                ssh_patches.main(),
                # init container for certs must come before all other init containers
                # so that it runs first before all other init containers
                init_containers_patches.certificates(),
                init_containers_patches.download_image(self),
                init_containers_patches.git_clone(self),
                inject_certificates_patches.proxy(self),
                # Cloud Storage needs to patch the git clone sidecar spec and so should come after
                # the sidecars
                # WARN: this patch depends on the index of the sidecar and so needs to be updated
                # if sidercars are added or removed
                cloudstorage_patches.main(self),
            )
        )

    def get_labels(self) -> dict[str, str | None]:
        prefix = self._get_renku_annotation_prefix()
        labels = {
            "app": "jupyter",
            "component": "singleuser-server",
            f"{prefix}commit-sha": None,
            f"{prefix}gitlabProjectId": None,
            f"{prefix}safe-username": self.safe_username,
            f"{prefix}quota": self.server_options.priority_class,
            f"{prefix}userId": self._user.id,
        }
        return labels

    def get_annotations(self) -> dict[str, str | None]:
        prefix = self._get_renku_annotation_prefix()
        annotations = {
            f"{prefix}commit-sha": None,
            f"{prefix}gitlabProjectId": None,
            f"{prefix}safe-username": self._user.safe_username,
            f"{prefix}username": self._user.username,
            f"{prefix}userId": self._user.id,
            f"{prefix}servername": self.server_name,
            f"{prefix}branch": None,
            f"{prefix}git-host": None,
            f"{prefix}namespace": None,
            f"{prefix}projectName": None,
            f"{prefix}requested-image": self.image,
            f"{prefix}repository": None,
            f"{prefix}hibernation": "",
            f"{prefix}hibernationBranch": "",
            f"{prefix}hibernationCommitSha": "",
            f"{prefix}hibernationDirty": "",
            f"{prefix}hibernationSynchronized": "",
            f"{prefix}hibernationDate": "",
            f"{prefix}hibernatedSecondsThreshold": str(
                self.hibernated_seconds_threshold
            ),
            f"{prefix}lastActivityDate": "",
            f"{prefix}idleSecondsThreshold": str(self.idle_seconds_threshold),
        }
        if self.server_options.resource_class_id:
            annotations[f"{prefix}resourceClassId"] = str(
                self.server_options.resource_class_id
            )
        return annotations


class Renku1UserServer(UserServer):
    """Represents a Renku 1.0 server session."""

    def __init__(
        self,
        user: AnonymousUser | RegisteredUser,
        server_name: str,
        namespace: str,
        project: str,
        branch: str,
        commit_sha: str,
        notebook: str | None,  # TODO: Is this value actually needed?
        image: str | None,
        server_options: ServerOptions,
        environment_variables: dict[str, str],
        user_secrets: K8sUserSecrets | None,
        cloudstorage: list[ICloudStorageRequest],
        k8s_client: K8sClient,
        workspace_mount_path: Path,
        work_dir: Path,
        using_default_image: bool = False,
        is_image_private: bool = False,
        **_,
    ):
        gitlab_project_name = f"{namespace}/{project}"
        gitlab_project = user.get_renku_project(gitlab_project_name)
        single_repository = (
            Repository(
                url=gitlab_project.http_url_to_repo,
                dirname=gitlab_project.path,
                branch=branch,
                commit_sha=commit_sha,
            )
            if gitlab_project is not None
            else None
        )

        super().__init__(
            user=user,
            server_name=server_name,
            image=image,
            server_options=server_options,
            environment_variables=environment_variables,
            user_secrets=user_secrets,
            cloudstorage=cloudstorage,
            k8s_client=k8s_client,
            workspace_mount_path=workspace_mount_path,
            work_dir=work_dir,
            using_default_image=using_default_image,
            is_image_private=is_image_private,
            repositories=[single_repository] if single_repository is not None else [],
        )

        self.namespace = namespace
        self.project = project
        self.branch = branch
        self.commit_sha = commit_sha
        self.notebook = notebook
        self.git_host = urlparse(config.git.url).netloc
        self.gitlab_project_name = gitlab_project_name
        self.gitlab_project = gitlab_project
        self.single_repository = single_repository

    def _get_start_errors(self) -> list[str]:
        """Check if there are any errors before starting the server."""
        errors = super()._get_start_errors()
        if self.gitlab_project is None:
            errors.append(f"project {self.project} does not exist")
        if not self._branch_exists():
            errors.append(f"branch {self.branch} does not exist")
        if not self._commit_sha_exists():
            errors.append(f"commit {self.commit_sha} does not exist")
        return errors

    def _branch_exists(self):
        """Check if a specific branch exists in the user's gitlab project.

        The branch name is not required by the API and therefore
        passing None to this function will return True.
        """
        if self.branch is not None and self.gitlab_project is not None:
            try:
                self.gitlab_project.branches.get(self.branch)
            except Exception as err:
                current_app.logger.warning(
                    f"Branch {self.branch} cannot be verified or does not exist. {err}"
                )
            else:
                return True
        return False

    def _commit_sha_exists(self):
        """Check if a specific commit sha exists in the user's gitlab project."""
        if self.commit_sha is not None and self.gitlab_project is not None:
            try:
                self.gitlab_project.commits.get(self.commit_sha)
            except Exception as err:
                current_app.logger.warning(
                    f"Commit {self.commit_sha} cannot be verified or does not exist. {err}"
                )
            else:
                return True
        return False

    def get_labels(self) -> dict[str, str | None]:
        prefix = self._get_renku_annotation_prefix()
        labels = super().get_labels()
        labels[f"{prefix}commit-sha"] = self.commit_sha
        if self.gitlab_project is not None:
            labels[f"{prefix}gitlabProjectId"] = str(self.gitlab_project.id)
        return labels

    def get_annotations(self) -> dict[str, str | None]:
        prefix = self._get_renku_annotation_prefix()
        annotations = super().get_annotations()
        annotations[f"{prefix}commit-sha"] = self.commit_sha
        annotations[f"{prefix}branch"] = self.branch
        annotations[f"{prefix}git-host"] = self.git_host
        annotations[f"{prefix}namespace"] = self.namespace
        annotations[f"{prefix}projectName"] = self.project
        if self.gitlab_project is not None:
            annotations[f"{prefix}gitlabProjectId"] = str(self.gitlab_project.id)
            annotations[f"{prefix}repository"] = self.gitlab_project.web_url
        return annotations


class Renku2UserServer(UserServer):
    """Represents a Renku 2.0 server session."""

    def __init__(
        self,
        user: AnonymousUser | RegisteredUser,
        image: str,
        project_id: str,
        launcher_id: str,
        server_name: str,
        server_options: ServerOptions,
        environment_variables: dict[str, str],
        user_secrets: K8sUserSecrets | None,
        cloudstorage: list[ICloudStorageRequest],
        k8s_client: K8sClient,
        workspace_mount_path: Path,
        work_dir: Path,
        repositories: list[Repository],
        using_default_image: bool = False,
        is_image_private: bool = False,
        **_,
    ):
        super().__init__(
            user=user,
            server_name=server_name,
            image=image,
            server_options=server_options,
            environment_variables=environment_variables,
            user_secrets=user_secrets,
            cloudstorage=cloudstorage,
            k8s_client=k8s_client,
            workspace_mount_path=workspace_mount_path,
            work_dir=work_dir,
            using_default_image=using_default_image,
            is_image_private=is_image_private,
            repositories=repositories,
        )

        self.project_id = project_id
        self.launcher_id = launcher_id

    def get_annotations(self):
        prefix = self._get_renku_annotation_prefix()
        annotations = super().get_annotations()
        annotations[f"{prefix}renkuVersion"] = "2.0"
        annotations[f"{prefix}projectId"] = self.project_id
        annotations[f"{prefix}launcherId"] = self.launcher_id
        return annotations
