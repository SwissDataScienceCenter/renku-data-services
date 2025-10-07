"""Jupyter server models."""

from collections.abc import Sequence
from itertools import chain
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urlparse

from gitlab.v4.objects.projects import Project

from renku_data_services.app_config import logging
from renku_data_services.base_models import AnonymousAPIUser, AuthenticatedAPIUser
from renku_data_services.base_models.core import APIUser
from renku_data_services.k8s.constants import DEFAULT_K8S_CLUSTER
from renku_data_services.notebooks.api.amalthea_patches import cloudstorage as cloudstorage_patches
from renku_data_services.notebooks.api.amalthea_patches import general as general_patches
from renku_data_services.notebooks.api.amalthea_patches import git_proxy as git_proxy_patches
from renku_data_services.notebooks.api.amalthea_patches import git_sidecar as git_sidecar_patches
from renku_data_services.notebooks.api.amalthea_patches import init_containers as init_containers_patches
from renku_data_services.notebooks.api.amalthea_patches import inject_certificates as inject_certificates_patches
from renku_data_services.notebooks.api.amalthea_patches import jupyter_server as jupyter_server_patches
from renku_data_services.notebooks.api.amalthea_patches import ssh as ssh_patches
from renku_data_services.notebooks.api.classes.cloud_storage import ICloudStorageRequest
from renku_data_services.notebooks.api.classes.k8s_client import NotebookK8sClient
from renku_data_services.notebooks.api.classes.repository import GitProvider, Repository
from renku_data_services.notebooks.api.schemas.secrets import K8sUserSecrets
from renku_data_services.notebooks.api.schemas.server_options import ServerOptions
from renku_data_services.notebooks.config import GitProviderHelperProto, NotebooksConfig
from renku_data_services.notebooks.constants import JUPYTER_SESSION_GVK
from renku_data_services.notebooks.cr_amalthea_session import TlsSecret
from renku_data_services.notebooks.crs import JupyterServerV1Alpha1
from renku_data_services.notebooks.errors.programming import DuplicateEnvironmentVariableError
from renku_data_services.notebooks.errors.user import MissingResourceError

logger = logging.getLogger(__name__)


class UserServer:
    """Represents a Renku server session."""

    def __init__(
        self,
        user: AnonymousAPIUser | AuthenticatedAPIUser,
        server_name: str,
        image: str | None,
        server_options: ServerOptions,
        environment_variables: dict[str, str],
        user_secrets: K8sUserSecrets | None,
        cloudstorage: Sequence[ICloudStorageRequest],
        k8s_client: NotebookK8sClient[JupyterServerV1Alpha1],
        workspace_mount_path: PurePosixPath,
        work_dir: PurePosixPath,
        config: NotebooksConfig,
        internal_gitlab_user: APIUser,
        host: str,
        namespace: str,
        git_provider_helper: GitProviderHelperProto,
        using_default_image: bool = False,
        is_image_private: bool = False,
        repositories: list[Repository] | None = None,
    ):
        self._user = user
        self.server_name = server_name
        self._k8s_client = k8s_client
        self.safe_username = self._user.id
        self.image = image
        self.server_options = server_options
        self.environment_variables = environment_variables
        self.user_secrets = user_secrets
        self.using_default_image = using_default_image
        self.workspace_mount_path = workspace_mount_path
        self.work_dir = work_dir
        self.cloudstorage = cloudstorage
        self.is_image_private = is_image_private
        self.host = host
        self.__namespace = namespace
        self.config = config
        self.git_provider_helper = git_provider_helper
        self.internal_gitlab_user = internal_gitlab_user

        if self.server_options.idle_threshold_seconds is not None:
            self.idle_seconds_threshold = self.server_options.idle_threshold_seconds
        else:
            self.idle_seconds_threshold = (
                config.sessions.culling.registered.idle_seconds
                if isinstance(self._user, AuthenticatedAPIUser)
                else config.sessions.culling.anonymous.idle_seconds
            )

        if self.server_options.hibernation_threshold_seconds is not None:
            self.hibernated_seconds_threshold: int = self.server_options.hibernation_threshold_seconds
        else:
            self.hibernated_seconds_threshold = (
                config.sessions.culling.registered.hibernated_seconds
                if isinstance(user, AuthenticatedAPIUser)
                else config.sessions.culling.anonymous.hibernated_seconds
            )
        self._repositories: list[Repository] = repositories or []
        self._git_providers: list[GitProvider] | None = None
        self._has_configured_git_providers = False

        self.server_url = f"https://{self.host}/sessions/{self.server_name}"
        if not self._user.is_authenticated:
            self.server_url = f"{self.server_url}?token={self._user.id}"

    def k8s_namespace(self) -> str:
        """Get the preferred namespace for a server."""
        return self.__namespace

    @property
    def user(self) -> AnonymousAPIUser | AuthenticatedAPIUser:
        """Getter for server's user."""
        return self._user

    async def repositories(self) -> list[Repository]:
        """Get the list of repositories in the project."""
        # Configure git repository providers based on matching URLs.
        if not self._has_configured_git_providers:
            git_providers = await self.git_providers()
            for repo in self._repositories:
                found_provider = None
                for provider in git_providers:
                    if urlparse(provider.url).netloc == urlparse(repo.url).netloc:
                        found_provider = provider
                        break
                if found_provider is not None:
                    repo.provider = found_provider.id
            self._has_configured_git_providers = True

        return self._repositories

    async def git_providers(self) -> list[GitProvider]:
        """The list of git providers."""
        if self._git_providers is None:
            self._git_providers = await self.git_provider_helper.get_providers(user=self.user)
        return self._git_providers

    async def required_git_providers(self) -> list[GitProvider]:
        """The list of required git providers."""
        repositories = await self.repositories()
        required_provider_ids: set[str] = set(r.provider for r in repositories if r.provider)
        providers = await self.git_providers()
        return [p for p in providers if p.id in required_provider_ids]

    def __str__(self) -> str:
        return f"<UserServer user: {self._user.id} server_name: {self.server_name}>"

    async def start(self) -> JupyterServerV1Alpha1 | None:
        """Create the jupyterserver resource in k8s."""
        errors = self._get_start_errors()
        if errors:
            raise MissingResourceError(
                message=(
                    "Cannot start the session because the following Git "
                    f"or Docker resources are missing: {', '.join(errors)}"
                )
            )
        session_manifest = await self._get_session_manifest()
        manifest = JupyterServerV1Alpha1.model_validate(session_manifest)
        return await self._k8s_client.create_session(manifest, self.user)

    @staticmethod
    def _check_environment_variables_overrides(patches_list: list[dict[str, Any]]) -> None:
        """Check if any patch overrides server's environment variables.

        Checks if it overrides with a different value or if two patches create environment variables with different
        values.
        """
        env_vars: dict[tuple[str, str], str] = {}

        for patch_list in patches_list:
            patches = patch_list["patch"]

            for patch in patches:
                path = str(patch["path"]).lower()
                if path.endswith("/env/-"):
                    name = str(patch["value"]["name"])
                    value = str(patch["value"]["value"])
                    key = (path, name)

                    if key in env_vars and env_vars[key] != value:
                        raise DuplicateEnvironmentVariableError(
                            message=f"Environment variable {path}::{name} is being overridden by multiple patches"
                        )
                    else:
                        env_vars[key] = value

    def _get_start_errors(self) -> list[str]:
        """Check if there are any errors before starting the server."""
        errors: list[str] = []
        if self.image is None:
            errors.append(f"image {self.image} does not exist or cannot be accessed")
        return errors

    async def _get_session_manifest(self) -> dict[str, Any]:
        """Compose the body of the user session for the k8s operator."""
        patches = await self._get_patches()
        self._check_environment_variables_overrides(patches)

        # Storage
        if self.config.sessions.storage.pvs_enabled:
            storage: dict[str, Any] = {
                "size": self.server_options.storage,
                "pvc": {
                    "enabled": True,
                    # We should check against the cluster, but as this is only used by V1 sessions, we ignore this
                    # use-case.
                    "storageClassName": self.config.sessions.storage.pvs_storage_class,
                    "mountPath": self.workspace_mount_path.as_posix(),
                },
            }
        else:
            storage_size = self.server_options.storage if self.config.sessions.storage.use_empty_dir_size_limit else ""
            storage = {
                "size": storage_size,
                "pvc": {
                    "enabled": False,
                    "mountPath": self.workspace_mount_path.as_posix(),
                },
            }
        # Authentication
        if isinstance(self._user, AuthenticatedAPIUser):
            session_auth = {
                "token": "",
                "oidc": {
                    "enabled": True,
                    "clientId": self.config.sessions.oidc.client_id,
                    "clientSecret": {"value": self.config.sessions.oidc.client_secret},
                    "issuerUrl": self.config.sessions.oidc.issuer_url,
                    "authorizedEmails": [self._user.email],
                },
            }
        else:
            session_auth = {
                "token": self._user.id,
                "oidc": {"enabled": False},
            }

        cluster = await self.config.k8s_client.cluster_by_class_id(self.server_options.resource_class_id, self._user)

        if cluster.id != DEFAULT_K8S_CLUSTER:
            cluster_settings = await self.config.cluster_rp.select(cluster.id)
            (
                base_server_path,
                _,
                _,
                host,
                tls_secret,
                _,
                ingress_annotations,
            ) = cluster_settings.get_ingress_parameters(self.server_name)
        else:
            # Fallback to global, main cluster parameters
            host = self.config.sessions.ingress.host
            base_server_path = self.config.sessions.ingress.base_path(self.server_name)
            ingress_annotations = self.config.sessions.ingress.annotations

            tls_name = self.config.sessions.ingress.tls_secret
            tls_secret = None if tls_name is None else TlsSecret(adopt=False, name=tls_name)

        # Combine everything into the manifest
        manifest = {
            "apiVersion": JUPYTER_SESSION_GVK.group_version,
            "kind": JUPYTER_SESSION_GVK.kind,
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
                        self.config.sessions.culling.registered.max_age_seconds
                        if isinstance(self._user, AuthenticatedAPIUser)
                        else self.config.sessions.culling.anonymous.max_age_seconds
                    ),
                    "hibernatedSecondsThreshold": self.hibernated_seconds_threshold,
                },
                "jupyterServer": {
                    "defaultUrl": self.server_options.default_url,
                    "image": self.image,
                    "rootDir": self.work_dir.as_posix(),
                    "resources": self.server_options.to_k8s_resources(
                        enforce_cpu_limits=self.config.sessions.enforce_cpu_limits
                    ),
                },
                "routing": {
                    "host": host,
                    "path": base_server_path,
                    "ingressAnnotations": ingress_annotations,
                    "tls": {
                        "enabled": tls_secret is not None,
                        "secretName": tls_secret.name if tls_secret is not None else "",
                    },
                },
                "storage": storage,
                "patches": patches,
            },
        }
        return manifest

    def _get_renku_annotation_prefix(self) -> str:
        return self.config.session_get_endpoint_annotations.renku_annotation_prefix

    async def _get_patches(self) -> list[dict[str, Any]]:
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
                jupyter_server_patches.image_pull_secret(self, self.internal_gitlab_user.access_token),
                jupyter_server_patches.disable_service_links(),
                jupyter_server_patches.rstudio_env_variables(self),
                await git_proxy_patches.main(self),
                await git_sidecar_patches.main(self),
                general_patches.oidc_unverified_email(self),
                ssh_patches.main(self.config),
                # init container for certs must come before all other init containers
                # so that it runs first before all other init containers
                init_containers_patches.certificates(self.config),
                init_containers_patches.download_image(self),
                await init_containers_patches.git_clone(self),
                inject_certificates_patches.proxy(self),
                # Cloud Storage needs to patch the git clone sidecar spec and so should come after
                # the sidecars
                # WARN: this patch depends on the index of the sidecar and so needs to be updated
                # if sidecars are added or removed
                await cloudstorage_patches.main(self),
                # NOTE: User secrets adds an init container, volume and mounts, so it may affect
                # indices in other patches.
                jupyter_server_patches.user_secrets(self),
            )
        )

    def get_labels(self) -> dict[str, str | None]:
        """Get the labels for the session."""
        prefix = self._get_renku_annotation_prefix()
        labels = {
            "app": "jupyter",
            "component": "singleuser-server",
            f"{prefix}commit-sha": None,
            f"{prefix}gitlabProjectId": None,
            f"{prefix}safe-username": self.safe_username,
            f"{prefix}quota": self.server_options.priority_class
            if self.server_options.priority_class is not None
            else "",
            f"{prefix}userId": self._user.id,
        }
        return labels

    def get_annotations(self) -> dict[str, str | None]:
        """Get the annotations for the session."""
        prefix = self._get_renku_annotation_prefix()
        username = self._user.id
        if isinstance(self.user, AuthenticatedAPIUser) and self._user.email:
            username = self._user.email
        annotations = {
            f"{prefix}commit-sha": None,
            f"{prefix}gitlabProjectId": None,
            f"{prefix}safe-username": self._user.id,
            f"{prefix}username": username,
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
            f"{prefix}hibernatedSecondsThreshold": str(self.hibernated_seconds_threshold),
            f"{prefix}lastActivityDate": "",
            f"{prefix}idleSecondsThreshold": str(self.idle_seconds_threshold),
        }
        if self.server_options.resource_class_id:
            annotations[f"{prefix}resourceClassId"] = str(self.server_options.resource_class_id)
        return annotations


class Renku1UserServer(UserServer):
    """Represents a Renku 1.0 server session."""

    def __init__(
        self,
        user: AnonymousAPIUser | AuthenticatedAPIUser,
        server_name: str,
        gl_namespace: str,
        project: str,
        branch: str,
        commit_sha: str,
        image: str | None,
        server_options: ServerOptions,
        environment_variables: dict[str, str],
        user_secrets: K8sUserSecrets | None,
        cloudstorage: Sequence[ICloudStorageRequest],
        k8s_client: NotebookK8sClient,
        workspace_mount_path: PurePosixPath,
        work_dir: PurePosixPath,
        config: NotebooksConfig,
        host: str,
        namespace: str,
        git_provider_helper: GitProviderHelperProto,
        gitlab_project: Project | None,
        internal_gitlab_user: APIUser,
        using_default_image: bool = False,
        is_image_private: bool = False,
        **_: dict,  # Required to ignore unused arguments, among which repositories
    ):
        repositories = [
            Repository(
                url=p.http_url_to_repo,
                dirname=p.path,
                branch=branch,
                commit_sha=commit_sha,
            )
            for p in [gitlab_project]
            if p is not None
        ]

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
            git_provider_helper=git_provider_helper,
            using_default_image=using_default_image,
            is_image_private=is_image_private,
            repositories=repositories,
            host=host,
            namespace=namespace,
            config=config,
            internal_gitlab_user=internal_gitlab_user,
        )

        self.gl_namespace = gl_namespace
        self.project = project
        self.branch = branch
        self.commit_sha = commit_sha
        self.git_host = urlparse(config.git.url).netloc
        self.gitlab_project = gitlab_project

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

    def _branch_exists(self) -> bool:
        """Check if a specific branch exists in the user's gitlab project.

        The branch name is not required by the API and therefore
        passing None to this function will return True.
        """
        if self.branch is not None and self.gitlab_project is not None:
            try:
                self.gitlab_project.branches.get(self.branch)
            except Exception as err:
                logger.warning(f"Branch {self.branch} cannot be verified or does not exist. {err}")
            else:
                return True
        return False

    def _commit_sha_exists(self) -> bool:
        """Check if a specific commit sha exists in the user's gitlab project."""
        if self.commit_sha is not None and self.gitlab_project is not None:
            try:
                self.gitlab_project.commits.get(self.commit_sha)
            except Exception as err:
                logger.warning(f"Commit {self.commit_sha} cannot be verified or does not exist. {err}")
            else:
                return True
        return False

    def get_labels(self) -> dict[str, str | None]:
        """Get the labels of the jupyter server."""
        prefix = self._get_renku_annotation_prefix()
        labels = super().get_labels()
        labels[f"{prefix}commit-sha"] = self.commit_sha
        if self.gitlab_project is not None:
            labels[f"{prefix}gitlabProjectId"] = str(self.gitlab_project.id)
        return labels

    def get_annotations(self) -> dict[str, str | None]:
        """Get the annotations of the jupyter server."""
        prefix = self._get_renku_annotation_prefix()
        annotations = super().get_annotations()
        annotations[f"{prefix}commit-sha"] = self.commit_sha
        annotations[f"{prefix}branch"] = self.branch
        annotations[f"{prefix}git-host"] = self.git_host
        annotations[f"{prefix}namespace"] = self.gl_namespace
        annotations[f"{prefix}projectName"] = self.project
        if self.gitlab_project is not None:
            annotations[f"{prefix}gitlabProjectId"] = str(self.gitlab_project.id)
            annotations[f"{prefix}repository"] = self.gitlab_project.web_url
        return annotations
