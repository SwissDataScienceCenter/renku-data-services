"""Notebooks service API."""

import base64
import json as json_lib
import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from math import floor
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from gitlab.const import Visibility as GitlabVisibility
from gitlab.v4.objects.projects import Project as GitlabProject
from kubernetes.client import V1ObjectMeta, V1Secret
from marshmallow import ValidationError
from sanic import Request, empty, exceptions, json
from sanic.log import logger
from sanic.response import HTTPResponse, JSONResponse
from sanic_ext import validate
from toml import dumps
from ulid import ULID
from yaml import safe_dump

from renku_data_services import base_models
from renku_data_services.base_api.auth import authenticate, authenticate_2
from renku_data_services.base_api.blueprint import BlueprintFactoryResponse, CustomBlueprint
from renku_data_services.base_models import AnonymousAPIUser, APIUser, AuthenticatedAPIUser, Authenticator
from renku_data_services.crc.db import ResourcePoolRepository
from renku_data_services.errors import errors
from renku_data_services.notebooks import apispec
from renku_data_services.notebooks.api.amalthea_patches import git_proxy, init_containers
from renku_data_services.notebooks.api.classes.auth import GitlabToken, RenkuTokens
from renku_data_services.notebooks.api.classes.image import Image
from renku_data_services.notebooks.api.classes.repository import Repository
from renku_data_services.notebooks.api.classes.server import Renku1UserServer, Renku2UserServer, UserServer
from renku_data_services.notebooks.api.classes.server_manifest import UserServerManifest
from renku_data_services.notebooks.api.classes.user import NotebooksGitlabClient
from renku_data_services.notebooks.api.schemas.cloud_storage import RCloneStorage
from renku_data_services.notebooks.api.schemas.config_server_options import ServerOptionsEndpointResponse
from renku_data_services.notebooks.api.schemas.logs import ServerLogs
from renku_data_services.notebooks.api.schemas.secrets import K8sUserSecrets
from renku_data_services.notebooks.api.schemas.server_options import ServerOptions
from renku_data_services.notebooks.api.schemas.servers_get import (
    NotebookResponse,
    ServersGetResponse,
)
from renku_data_services.notebooks.api.schemas.servers_patch import PatchServerStatusEnum
from renku_data_services.notebooks.config import _NotebooksConfig
from renku_data_services.notebooks.crs import (
    AmaltheaSessionSpec,
    AmaltheaSessionV1Alpha1,
    Authentication,
    AuthenticationType,
    Culling,
    ExtraContainer,
    ExtraVolume,
    ExtraVolumeMount,
    Ingress,
    InitContainer,
    Metadata,
    Resources,
    SecretAsVolume,
    SecretAsVolumeItem,
    SecretRef,
    Session,
    SessionEnvItem,
    State,
    Storage,
    TlsSecret,
)
from renku_data_services.notebooks.errors.intermittent import AnonymousUserPatchError, PVDisabledError
from renku_data_services.notebooks.errors.programming import ProgrammingError
from renku_data_services.notebooks.errors.user import MissingResourceError, UserInputError
from renku_data_services.notebooks.util.kubernetes_ import (
    find_container,
    renku_1_make_server_name,
    renku_2_make_server_name,
)
from renku_data_services.notebooks.util.repository import get_status
from renku_data_services.project.db import ProjectRepository
from renku_data_services.repositories.db import GitRepositoriesRepository
from renku_data_services.session.db import SessionRepository


@dataclass(kw_only=True)
class NotebooksBP(CustomBlueprint):
    """Handlers for manipulating notebooks."""

    authenticator: Authenticator
    nb_config: _NotebooksConfig
    git_repo: GitRepositoriesRepository
    internal_gitlab_authenticator: base_models.Authenticator

    def version(self) -> BlueprintFactoryResponse:
        """Return notebook services version."""

        async def _version(_: Request) -> JSONResponse:
            culling = self.nb_config.sessions.culling
            info = {
                "name": "renku-notebooks",
                "versions": [
                    {
                        "version": self.nb_config.version,
                        "data": {
                            "anonymousSessionsEnabled": self.nb_config.anonymous_sessions_enabled,
                            "cloudstorageEnabled": self.nb_config.cloud_storage.enabled,
                            "cloudstorageClass": self.nb_config.cloud_storage.storage_class,
                            "sshEnabled": self.nb_config.ssh_enabled,
                            "defaultCullingThresholds": {
                                "registered": {
                                    "idle": culling.registered.idle_seconds,
                                    "hibernation": culling.registered.hibernated_seconds,
                                },
                                "anonymous": {
                                    "idle": culling.anonymous.idle_seconds,
                                    "hibernation": culling.anonymous.hibernated_seconds,
                                },
                            },
                        },
                    }
                ],
            }
            return json(info)

        return "/notebooks/version", ["GET"], _version

    def user_servers(self) -> BlueprintFactoryResponse:
        """Return a JSON of running servers for the user."""

        @authenticate(self.authenticator)
        async def _user_servers(
            request: Request, user: AnonymousAPIUser | AuthenticatedAPIUser, **query_params: dict
        ) -> JSONResponse:
            servers = [
                UserServerManifest(s, self.nb_config.sessions.default_image)
                for s in await self.nb_config.k8s_client.list_servers(user.id)
            ]
            filter_attrs = list(filter(lambda x: x[1] is not None, request.get_query_args()))
            filtered_servers = {}
            ann_prefix = self.nb_config.session_get_endpoint_annotations.renku_annotation_prefix
            for server in servers:
                if all([server.annotations.get(f"{ann_prefix}{key}") == value for key, value in filter_attrs]):
                    filtered_servers[server.server_name] = server
            return json(ServersGetResponse().dump({"servers": filtered_servers}))

        return "/notebooks/servers", ["GET"], _user_servers

    def user_server(self) -> BlueprintFactoryResponse:
        """Returns a user server based on its ID."""

        @authenticate(self.authenticator)
        async def _user_server(
            request: Request, user: AnonymousAPIUser | AuthenticatedAPIUser, server_name: str
        ) -> JSONResponse:
            server = await self.nb_config.k8s_client.get_server(server_name, user.id)
            if server is None:
                raise MissingResourceError(message=f"The server {server_name} does not exist.")
            server = UserServerManifest(server, self.nb_config.sessions.default_image)
            return json(NotebookResponse().dump(server))

        return "/notebooks/servers/<server_name>", ["GET"], _user_server

    def launch_notebook(self) -> BlueprintFactoryResponse:
        """Start a renku session."""

        @authenticate_2(self.authenticator, self.internal_gitlab_authenticator)
        @validate(json=apispec.LaunchNotebookRequest)
        async def _launch_notebook(
            request: Request,
            user: AnonymousAPIUser | AuthenticatedAPIUser,
            internal_gitlab_user: APIUser,
            body: apispec.LaunchNotebookRequest,
        ) -> JSONResponse:
            server_name = renku_2_make_server_name(
                safe_username=user.id, project_id=body.project_id, launcher_id=body.launcher_id
            )
            server_class = Renku2UserServer
            server, status_code = await self.launch_notebook_helper(
                nb_config=self.nb_config,
                server_name=server_name,
                server_class=server_class,
                user=user,
                image=body.image or self.nb_config.sessions.default_image,
                resource_class_id=body.resource_class_id,
                storage=body.storage,
                environment_variables=body.environment_variables,
                user_secrets=body.user_secrets,
                default_url=self.nb_config.server_options.default_url_default,
                lfs_auto_fetch=self.nb_config.server_options.lfs_auto_fetch_default,
                cloudstorage=body.cloudstorage,
                server_options=None,
                namespace=None,
                project=None,
                branch=None,
                commit_sha=None,
                notebook=None,
                gl_project=None,
                gl_project_path=None,
                project_id=body.project_id,
                launcher_id=body.launcher_id,
                repositories=body.repositories,
                internal_gitlab_user=internal_gitlab_user,
            )
            return json(NotebookResponse().dump(server), status_code)

        return "/notebooks/servers", ["POST"], _launch_notebook

    def launch_notebook_old(self) -> BlueprintFactoryResponse:
        """Start a renku session using the old operator."""

        @authenticate_2(self.authenticator, self.internal_gitlab_authenticator)
        @validate(json=apispec.LaunchNotebookRequestOld)
        async def _launch_notebook_old(
            request: Request,
            user: AnonymousAPIUser | AuthenticatedAPIUser,
            internal_gitlab_user: APIUser,
            body: apispec.LaunchNotebookRequestOld,
        ) -> JSONResponse:
            server_name = renku_1_make_server_name(user.id, body.namespace, body.project, body.branch, body.commit_sha)
            project_slug = f"{body.namespace}/{body.project}"
            gitlab_client = NotebooksGitlabClient(self.nb_config.git.url, APIUser.access_token)
            gl_project = gitlab_client.get_renku_project(project_slug)
            if gl_project is None:
                raise errors.MissingResourceError(message=f"Cannot find gitlab project with slug {project_slug}")
            gl_project_path = gl_project.path
            server_class = Renku1UserServer
            server_options = (
                ServerOptions.from_server_options_request_schema(
                    body.serverOptions.model_dump(),
                    self.nb_config.server_options.default_url_default,
                    self.nb_config.server_options.lfs_auto_fetch_default,
                )
                if body.serverOptions is not None
                else None
            )

            server, status_code = await self.launch_notebook_helper(
                nb_config=self.nb_config,
                server_name=server_name,
                server_class=server_class,
                user=user,
                image=body.image or self.nb_config.sessions.default_image,
                resource_class_id=body.resource_class_id,
                storage=body.storage,
                environment_variables=body.environment_variables,
                user_secrets=body.user_secrets,
                default_url=body.default_url,
                lfs_auto_fetch=body.lfs_auto_fetch,
                cloudstorage=body.cloudstorage,
                server_options=server_options,
                namespace=body.namespace,
                project=body.project,
                branch=body.branch,
                commit_sha=body.commit_sha,
                notebook=body.notebook,
                gl_project=gl_project,
                gl_project_path=gl_project_path,
                project_id=None,
                launcher_id=None,
                repositories=None,
                internal_gitlab_user=internal_gitlab_user,
            )
            return json(NotebookResponse().dump(server), status_code)

        return "/notebooks/old/servers", ["POST"], _launch_notebook_old

    @staticmethod
    async def launch_notebook_helper(
        nb_config: _NotebooksConfig,
        server_name: str,
        server_class: type[UserServer],
        user: AnonymousAPIUser | AuthenticatedAPIUser,
        image: str,
        resource_class_id: int | None,
        storage: int | None,
        environment_variables: dict[str, str],
        user_secrets: apispec.UserSecrets | None,
        default_url: str,
        lfs_auto_fetch: bool,
        cloudstorage: list[apispec.RCloneStorageRequest],
        server_options: ServerOptions | dict | None,
        namespace: str | None,  # Renku 1.0
        project: str | None,  # Renku 1.0
        branch: str | None,  # Renku 1.0
        commit_sha: str | None,  # Renku 1.0
        notebook: str | None,  # Renku 1.0
        gl_project: GitlabProject | None,  # Renku 1.0
        gl_project_path: str | None,  # Renku 1.0
        project_id: str | None,  # Renku 2.0
        launcher_id: str | None,  # Renku 2.0
        repositories: list[apispec.LaunchNotebookRequestRepository] | None,  # Renku 2.0
        internal_gitlab_user: APIUser,
    ) -> tuple[UserServerManifest, int]:
        """Helper function to launch a Jupyter server."""
        server = await nb_config.k8s_client.get_server(server_name, user.id)

        if server:
            return UserServerManifest(
                server, nb_config.sessions.default_image, nb_config.sessions.storage.pvs_enabled
            ), 200

        gl_project_path = gl_project_path if gl_project_path is not None else ""

        # Add annotation for old and new notebooks
        is_image_private = False
        using_default_image = False
        if image:
            # A specific image was requested
            parsed_image = Image.from_path(image)
            image_repo = parsed_image.repo_api()
            image_exists_publicly = image_repo.image_exists(parsed_image)
            image_exists_privately = False
            if (
                not image_exists_publicly
                and parsed_image.hostname == nb_config.git.registry
                and internal_gitlab_user.access_token
            ):
                image_repo = image_repo.with_oauth2_token(internal_gitlab_user.access_token)
                image_exists_privately = image_repo.image_exists(parsed_image)
            if not image_exists_privately and not image_exists_publicly:
                using_default_image = True
                image = nb_config.sessions.default_image
                parsed_image = Image.from_path(image)
            if image_exists_privately:
                is_image_private = True
        elif gl_project is not None:
            # An image was not requested specifically, use the one automatically built for the commit
            if commit_sha is None:
                raise errors.ValidationError(
                    message="Cannot run a session with an image based on a commit sha if the commit sha is not known."
                )
            image = f"{nb_config.git.registry}/{gl_project.path_with_namespace.lower()}:{commit_sha[:7]}"
            parsed_image = Image(
                nb_config.git.registry,
                gl_project.path_with_namespace.lower(),
                commit_sha[:7],
            )
            # NOTE: a project pulled from the Gitlab API without credentials has no visibility attribute
            # and by default it can only be public since only public projects are visible to
            # non-authenticated users. Also, a nice footgun from the Gitlab API Python library.
            is_image_private = getattr(gl_project, "visibility", GitlabVisibility.PUBLIC) != GitlabVisibility.PUBLIC
            image_repo = parsed_image.repo_api()
            if is_image_private and internal_gitlab_user.access_token:
                image_repo = image_repo.with_oauth2_token(internal_gitlab_user.access_token)
            if not image_repo.image_exists(parsed_image):
                raise MissingResourceError(
                    message=(
                        f"Cannot start the session because the following the image {image} does not "
                        "exist or the user does not have the permissions to access it."
                    )
                )
        else:
            raise UserInputError(message="Cannot determine which Docker image to use.")

        parsed_server_options: ServerOptions | None = None
        if resource_class_id is not None:
            # A resource class ID was passed in, validate with CRC service
            parsed_server_options = await nb_config.crc_validator.validate_class_storage(
                user, resource_class_id, storage
            )
        elif server_options is not None:
            if isinstance(server_options, dict):
                requested_server_options = ServerOptions(
                    memory=server_options["mem_request"],
                    storage=server_options["disk_request"],
                    cpu=server_options["cpu_request"],
                    gpu=server_options["gpu_request"],
                    lfs_auto_fetch=server_options["lfs_auto_fetch"],
                    default_url=server_options["defaultUrl"],
                )
            elif isinstance(server_options, ServerOptions):
                requested_server_options = server_options
            else:
                raise ProgrammingError(
                    message="Got an unexpected type of server options when "
                    f"launching sessions: {type(server_options)}"
                )
            # The old style API was used, try to find a matching class from the CRC service
            parsed_server_options = await nb_config.crc_validator.find_acceptable_class(user, requested_server_options)
            if parsed_server_options is None:
                raise UserInputError(
                    message="Cannot find suitable server options based on your request and "
                    "the available resource classes.",
                    detail="You are receiving this error because you are using the old API for "
                    "selecting resources. Updating to the new API which includes specifying only "
                    "a specific resource class ID and storage is preferred and more convenient.",
                )
        else:
            # No resource class ID specified or old-style server options, use defaults from CRC
            default_resource_class = await nb_config.crc_validator.get_default_class()
            max_storage_gb = default_resource_class.max_storage
            if storage is not None and storage > max_storage_gb:
                raise UserInputError(
                    "The requested storage amount is higher than the "
                    f"allowable maximum for the default resource class of {max_storage_gb}GB."
                )
            if storage is None:
                storage = default_resource_class.default_storage
            parsed_server_options = ServerOptions.from_resource_class(default_resource_class)
            # Storage in request is in GB
            parsed_server_options.set_storage(storage, gigabytes=True)

        if default_url is not None:
            parsed_server_options.default_url = default_url

        if lfs_auto_fetch is not None:
            parsed_server_options.lfs_auto_fetch = lfs_auto_fetch

        image_work_dir = image_repo.image_workdir(parsed_image) or Path("/")
        mount_path = image_work_dir / "work"

        server_work_dir = mount_path / gl_project_path

        storages: list[RCloneStorage] = []
        if cloudstorage:
            gl_project_id = gl_project.id if gl_project is not None else 0
            try:
                for cstorage in cloudstorage:
                    storages.append(
                        await RCloneStorage.storage_from_schema(
                            cstorage.model_dump(),
                            user=user,
                            project_id=gl_project_id,
                            work_dir=server_work_dir.absolute(),
                            config=nb_config,
                            internal_gitlab_user=internal_gitlab_user,
                        )
                    )
            except ValidationError as e:
                raise UserInputError(f"Couldn't load cloud storage config: {str(e)}")
            mount_points = set(s.mount_folder for s in storages if s.mount_folder and s.mount_folder != "/")
            if len(mount_points) != len(storages):
                raise UserInputError(
                    "Storage mount points must be set, can't be at the root of the project and must be unique."
                )
            if any(s1.mount_folder.startswith(s2.mount_folder) for s1 in storages for s2 in storages if s1 != s2):
                raise UserInputError("Cannot mount a cloud storage into the mount point of another cloud storage.")

        repositories = repositories or []

        k8s_user_secret = None
        if user_secrets:
            k8s_user_secret = K8sUserSecrets(f"{server_name}-secret", **user_secrets.model_dump())

        extra_kwargs: dict = dict(
            commit_sha=commit_sha,
            branch=branch,
            project=project,
            namespace=namespace,
            launcher_id=launcher_id,
            project_id=project_id,
            notebook=notebook,
        )
        server = server_class(
            user=user,
            image=image,
            server_name=server_name,
            server_options=parsed_server_options,
            environment_variables=environment_variables,
            user_secrets=k8s_user_secret,
            cloudstorage=storages,
            k8s_client=nb_config.k8s_client,
            workspace_mount_path=mount_path,
            work_dir=server_work_dir,
            using_default_image=using_default_image,
            is_image_private=is_image_private,
            repositories=[Repository.from_dict(r.model_dump()) for r in repositories],
            config=nb_config,
            **extra_kwargs,
        )

        if len(server.safe_username) > 63:
            raise UserInputError(
                message="A username cannot be longer than 63 characters, "
                f"your username is {len(server.safe_username)} characters long.",
                detail="This can occur if your username has been changed manually or by an admin.",
            )

        manifest = await server.start()
        if manifest is None:
            raise errors.ProgrammingError(message="Failed to start server.")

        logging.debug(f"Server {server.server_name} has been started")

        if k8s_user_secret is not None:
            owner_reference = {
                "apiVersion": "amalthea.dev/v1alpha1",
                "kind": "JupyterServer",
                "name": server.server_name,
                "uid": manifest.metadata.uid,
                "controller": True,
            }
            request_data = {
                "name": k8s_user_secret.name,
                "namespace": server.k8s_client.preferred_namespace,
                "secret_ids": [str(id_) for id_ in k8s_user_secret.user_secret_ids],
                "owner_references": [owner_reference],
            }
            headers = {"Authorization": f"bearer {user.access_token}"}

            async def _on_error(server_name: str, error_msg: str) -> None:
                await nb_config.k8s_client.delete_server(server_name, safe_username=user.id)
                raise RuntimeError(error_msg)

            try:
                response = requests.post(
                    nb_config.user_secrets.secrets_storage_service_url + "/api/secrets/kubernetes",
                    json=request_data,
                    headers=headers,
                    timeout=10,
                )
            except requests.exceptions.ConnectionError:
                await _on_error(server.server_name, "User secrets storage service could not be contacted {exc}")

            if response.status_code != 201:
                await _on_error(server.server_name, f"User secret could not be created {response.json()}")

        return UserServerManifest(manifest, nb_config.sessions.default_image), 201

    def patch_server(self) -> BlueprintFactoryResponse:
        """Patch a user server by name based on the query param."""

        @authenticate_2(self.authenticator, self.internal_gitlab_authenticator)
        @validate(json=apispec.PatchServerRequest)
        async def _patch_server(
            request: Request,
            user: AnonymousAPIUser | AuthenticatedAPIUser,
            internal_gitlab_user: APIUser,
            server_name: str,
            body: apispec.PatchServerRequest,
        ) -> JSONResponse:
            if not self.nb_config.sessions.storage.pvs_enabled:
                raise PVDisabledError()

            if isinstance(user, AnonymousAPIUser):
                raise AnonymousUserPatchError()

            patch_body = body
            server = await self.nb_config.k8s_client.get_server(server_name, user.id)
            if server is None:
                raise errors.MissingResourceError(message=f"The server with name {server_name} cannot be found")
            if server.spec is None:
                raise errors.ProgrammingError(message="The server manifest is absent")

            new_server = server
            currently_hibernated = server.spec.jupyterServer.hibernated
            currently_failing = server.status.get("state", "running") == "failed"
            state = PatchServerStatusEnum.from_api_state(body.state) if body.state is not None else None
            resource_class_id = patch_body.resource_class_id
            if server and not (currently_hibernated or currently_failing) and resource_class_id:
                raise UserInputError("The resource class can be changed only if the server is hibernated or failing")

            if resource_class_id:
                parsed_server_options = await self.nb_config.crc_validator.validate_class_storage(
                    user,
                    resource_class_id,
                    storage=None,  # we do not care about validating storage
                )
                js_patch: list[dict[str, Any]] = [
                    {
                        "op": "replace",
                        "path": "/spec/jupyterServer/resources",
                        "value": parsed_server_options.to_k8s_resources(self.nb_config.sessions.enforce_cpu_limits),
                    },
                    {
                        "op": "replace",
                        # NOTE: ~1 is how you escape '/' in json-patch
                        "path": "/metadata/annotations/renku.io~1resourceClassId",
                        "value": str(resource_class_id),
                    },
                ]
                if parsed_server_options.priority_class:
                    js_patch.append(
                        {
                            "op": "replace",
                            # NOTE: ~1 is how you escape '/' in json-patch
                            "path": "/metadata/labels/renku.io~1quota",
                            "value": parsed_server_options.priority_class,
                        }
                    )
                elif server.metadata.labels.get("renku.io/quota"):
                    js_patch.append(
                        {
                            "op": "remove",
                            # NOTE: ~1 is how you escape '/' in json-patch
                            "path": "/metadata/labels/renku.io~1quota",
                        }
                    )
                new_server = await self.nb_config.k8s_client.patch_server(
                    server_name=server_name, safe_username=user.id, patch=js_patch
                )
                ss_patch: list[dict[str, Any]] = [
                    {
                        "op": "replace",
                        "path": "/spec/template/spec/priorityClassName",
                        "value": parsed_server_options.priority_class,
                    }
                ]
                await self.nb_config.k8s_client.patch_statefulset(server_name=server_name, patch=ss_patch)

            if state == PatchServerStatusEnum.Hibernated:
                # NOTE: Do nothing if server is already hibernated
                currently_hibernated = server.spec.jupyterServer.hibernated
                if server and currently_hibernated:
                    logger.warning(f"Server {server_name} is already hibernated.")

                    return json(
                        NotebookResponse().dump(UserServerManifest(server, self.nb_config.sessions.default_image)), 200
                    )

                hibernation: dict[str, str | bool] = {"branch": "", "commit": "", "dirty": "", "synchronized": ""}

                sidecar_patch = find_container(server.spec.patches, "git-sidecar")
                status = (
                    get_status(
                        server_name=server_name,
                        access_token=user.access_token,
                        hostname=self.nb_config.sessions.ingress.host,
                    )
                    if sidecar_patch is not None
                    else None
                )
                if status:
                    hibernation = {
                        "branch": status.get("branch", ""),
                        "commit": status.get("commit", ""),
                        "dirty": not status.get("clean", True),
                        "synchronized": status.get("ahead", 0) == status.get("behind", 0) == 0,
                    }

                hibernation["date"] = datetime.now(UTC).isoformat(timespec="seconds")

                patch = {
                    "metadata": {
                        "annotations": {
                            "renku.io/hibernation": json_lib.dumps(hibernation),
                            "renku.io/hibernationBranch": hibernation["branch"],
                            "renku.io/hibernationCommitSha": hibernation["commit"],
                            "renku.io/hibernationDirty": str(hibernation["dirty"]).lower(),
                            "renku.io/hibernationSynchronized": str(hibernation["synchronized"]).lower(),
                            "renku.io/hibernationDate": hibernation["date"],
                        },
                    },
                    "spec": {
                        "jupyterServer": {
                            "hibernated": True,
                        },
                    },
                }

                new_server = await self.nb_config.k8s_client.patch_server(
                    server_name=server_name, safe_username=user.id, patch=patch
                )
            elif state == PatchServerStatusEnum.Running:
                # NOTE: We clear hibernation annotations in Amalthea to avoid flickering in the UI (showing
                # the repository as dirty when resuming a session for a short period of time).
                patch = {
                    "spec": {
                        "jupyterServer": {
                            "hibernated": False,
                        },
                    },
                }
                # NOTE: The tokens in the session could expire if the session is hibernated long enough,
                # here we inject new ones to make sure everything is valid when the session starts back up.
                if user.access_token is None or user.refresh_token is None or internal_gitlab_user.access_token is None:
                    raise errors.UnauthorizedError(
                        message="Cannot patch the server if the user is not fully logged in."
                    )
                renku_tokens = RenkuTokens(access_token=user.access_token, refresh_token=user.refresh_token)
                gitlab_token = GitlabToken(
                    access_token=internal_gitlab_user.access_token,
                    expires_at=(
                        floor(user.access_token_expires_at.timestamp())
                        if user.access_token_expires_at is not None
                        else -1
                    ),
                )
                await self.nb_config.k8s_client.patch_tokens(server_name, renku_tokens, gitlab_token)
                new_server = await self.nb_config.k8s_client.patch_server(
                    server_name=server_name, safe_username=user.id, patch=patch
                )

            return json(
                NotebookResponse().dump(UserServerManifest(new_server, self.nb_config.sessions.default_image)), 200
            )

        return "/notebooks/servers/<server_name>", ["PATCH"], _patch_server

    def stop_server(self) -> BlueprintFactoryResponse:
        """Stop user server by name."""

        @authenticate(self.authenticator)
        async def _stop_server(
            request: Request, user: AnonymousAPIUser | AuthenticatedAPIUser, server_name: str
        ) -> HTTPResponse:
            try:
                await self.nb_config.k8s_client.delete_server(server_name, safe_username=user.id)
            except MissingResourceError as err:
                raise exceptions.NotFound(message=err.message)
            return HTTPResponse(status=204)

        return "/notebooks/servers/<server_name>", ["DELETE"], _stop_server

    def server_options(self) -> BlueprintFactoryResponse:
        """Return a set of configurable server options."""

        async def _server_options(request: Request) -> JSONResponse:
            return json(
                ServerOptionsEndpointResponse().dump(
                    {
                        **self.nb_config.server_options.ui_choices,
                        "cloudstorage": {
                            "enabled": self.nb_config.cloud_storage.enabled,
                        },
                    },
                )
            )

        return "/notebooks/server_options", ["GET"], _server_options

    def server_logs(self) -> BlueprintFactoryResponse:
        """Return the logs of the running server."""

        @authenticate(self.authenticator)
        async def _server_logs(
            request: Request, user: AnonymousAPIUser | AuthenticatedAPIUser, server_name: str
        ) -> JSONResponse:
            args: dict[str, str | int] = request.get_args()
            max_lines = int(args.get("max_lines", 250))
            try:
                logs = await self.nb_config.k8s_client.get_server_logs(
                    server_name=server_name,
                    safe_username=user.id,
                    max_log_lines=max_lines,
                )
                return json(ServerLogs().dump(logs))
            except MissingResourceError as err:
                raise exceptions.NotFound(message=err.message)

        return "/notebooks/logs/<server_name>", ["GET"], _server_logs

    def check_docker_image(self) -> BlueprintFactoryResponse:
        """Return the availability of the docker image."""

        @authenticate_2(self.authenticator, self.internal_gitlab_authenticator)
        async def _check_docker_image(
            request: Request, user: AnonymousAPIUser | AuthenticatedAPIUser, internal_gitlab_user: APIUser
        ) -> HTTPResponse:
            image_url = request.get_args().get("image_url")
            if not isinstance(image_url, str):
                raise ValueError("required string of image url")
            parsed_image = Image.from_path(image_url)
            image_repo = parsed_image.repo_api()
            if parsed_image.hostname == self.nb_config.git.registry and internal_gitlab_user.access_token:
                image_repo = image_repo.with_oauth2_token(internal_gitlab_user.access_token)
            if image_repo.image_exists(parsed_image):
                return HTTPResponse(status=200)
            else:
                return HTTPResponse(status=404)

        return "/notebooks/images", ["GET"], _check_docker_image


@dataclass(kw_only=True)
class NotebooksNewBP(CustomBlueprint):
    """Handlers for manipulating notebooks for the new Amalthea operator."""

    authenticator: base_models.Authenticator
    internal_gitlab_authenticator: base_models.Authenticator
    nb_config: _NotebooksConfig
    project_repo: ProjectRepository
    session_repo: SessionRepository
    rp_repo: ResourcePoolRepository

    def start(self) -> BlueprintFactoryResponse:
        """Start a session with the new operator."""

        @authenticate_2(self.authenticator, self.internal_gitlab_authenticator)
        @validate(json=apispec.SessionPostRequest)
        async def _handler(
            _: Request,
            user: AuthenticatedAPIUser | AnonymousAPIUser,
            internal_gitlab_user: APIUser,
            body: apispec.SessionPostRequest,
        ) -> JSONResponse:
            # gitlab_client = NotebooksGitlabClient(self.nb_config.git.url, internal_gitlab_user.access_token)
            launcher = await self.session_repo.get_launcher(user, ULID.from_str(body.launcher_id))
            project = await self.project_repo.get_project(user=user, project_id=launcher.project_id)
            server_name = renku_2_make_server_name(
                safe_username=user.id, project_id=str(launcher.project_id), launcher_id=body.launcher_id
            )
            existing_session = await self.nb_config.k8s_v2_client.get_server(server_name, user.id)
            if existing_session is not None and existing_session.spec is not None:
                return json(existing_session.as_apispec().model_dump(exclude_none=True, mode="json"))
            environment = launcher.environment
            image = environment.container_image
            default_resource_class = await self.rp_repo.get_default_resource_class()
            if default_resource_class.id is None:
                raise errors.ProgrammingError(message="The default reosurce class has to have an ID", quiet=True)
            resource_class_id = body.resource_class_id or default_resource_class.id
            parsed_server_options = await self.nb_config.crc_validator.validate_class_storage(
                user, resource_class_id, body.disk_storage
            )
            work_dir = Path("/home/jovyan/work")
            user_secrets: K8sUserSecrets | None = None
            # if body.user_secrets:
            #     user_secrets = K8sUserSecrets(
            #         name=server_name,
            #         user_secret_ids=body.user_secrets.user_secret_ids,
            #         mount_path=body.user_secrets.mount_path,
            #     )
            cloud_storage: list[RCloneStorage] = []
            # repositories = [Repository(i.url, branch=i.branch, commit_sha=i.commit_sha) for i in body.repositories]
            repositories = [Repository(url=i) for i in project.repositories]
            server = Renku2UserServer(
                user=user,
                image=image,
                project_id=str(launcher.project_id),
                launcher_id=body.launcher_id,
                server_name=server_name,
                server_options=parsed_server_options,
                environment_variables={},
                user_secrets=user_secrets,
                cloudstorage=cloud_storage,
                k8s_client=self.nb_config.k8s_v2_client,
                workspace_mount_path=work_dir,
                work_dir=work_dir,
                repositories=repositories,
                config=self.nb_config,
                using_default_image=self.nb_config.sessions.default_image == image,
                is_image_private=False,
                internal_gitlab_user=internal_gitlab_user,
            )
            cert_init, cert_vols = init_containers.certificates_container(self.nb_config)
            session_init_containers = [InitContainer.model_validate(self.nb_config.k8s_v2_client.sanitize(cert_init))]
            extra_volumes = [ExtraVolume.model_validate(self.nb_config.k8s_v2_client.sanitize(i)) for i in cert_vols]
            if isinstance(user, AuthenticatedAPIUser):
                extra_volumes.append(
                    ExtraVolume(
                        name="renku-authorized-emails",
                        secret=SecretAsVolume(
                            secretName=server_name,
                            items=[SecretAsVolumeItem(key="authorized_emails", path="authorized_emails")],
                        ),
                    )
                )
            git_clone = await init_containers.git_clone_container_v2(server)
            if git_clone is not None:
                session_init_containers.append(InitContainer.model_validate(git_clone))
            extra_containers: list[ExtraContainer] = []
            git_proxy_container = await git_proxy.main_container(server)
            if git_proxy_container is not None:
                extra_containers.append(
                    ExtraContainer.model_validate(self.nb_config.k8s_v2_client.sanitize(git_proxy_container))
                )

            parsed_server_url = urlparse(server.server_url)
            annotations: dict[str, str] = {
                "renku.io/project_id": str(launcher.project_id),
                "renku.io/launcher_id": body.launcher_id,
                "renku.io/resource_class_id": str(body.resource_class_id or default_resource_class.id),
            }
            manifest = AmaltheaSessionV1Alpha1(
                metadata=Metadata(name=server_name, annotations=annotations),
                spec=AmaltheaSessionSpec(
                    codeRepositories=[],
                    dataSources=[],
                    hibernated=False,
                    session=Session(
                        image=image,
                        urlPath=parsed_server_url.path,
                        port=environment.port,
                        storage=Storage(
                            className=self.nb_config.sessions.storage.pvs_storage_class,
                            size=str(body.disk_storage) + "G",
                            mountPath=environment.mount_directory.as_posix(),
                        ),
                        workingDir=environment.working_directory.as_posix(),
                        runAsUser=environment.uid,
                        runAsGroup=environment.gid,
                        resources=Resources(claims=None, requests=None, limits=None),
                        extraVolumeMounts=[],
                        command=environment.command,
                        args=environment.args,
                        shmSize="1G",
                        env=[
                            SessionEnvItem(name="RENKU_BASE_URL_PATH", value=parsed_server_url.path),
                            SessionEnvItem(name="RENKU_BASE_URL", value=server.server_url),
                        ],
                    ),
                    ingress=Ingress(
                        host=self.nb_config.sessions.ingress.host,
                        ingressClassName=self.nb_config.sessions.ingress.annotations.get("kubernetes.io/ingress.class"),
                        annotations=self.nb_config.sessions.ingress.annotations,
                        tlsSecret=TlsSecret(adopt=False, name=self.nb_config.sessions.ingress.tls_secret)
                        if self.nb_config.sessions.ingress.tls_secret is not None
                        else None,
                    ),
                    extraContainers=extra_containers,
                    initContainers=session_init_containers,
                    extraVolumes=extra_volumes,
                    culling=Culling(
                        maxAge=f"{self.nb_config.sessions.culling.registered.max_age_seconds}s",
                        maxFailedDuration=f"{self.nb_config.sessions.culling.registered.failed_seconds}s",
                        maxHibernatedDuration=f"{self.nb_config.sessions.culling.registered.hibernated_seconds}s",
                        maxIdleDuration=f"{self.nb_config.sessions.culling.registered.idle_seconds}s",
                        maxStartingDuration=f"{self.nb_config.sessions.culling.registered.pending_seconds}s",
                    ),
                    authentication=Authentication(
                        enabled=True,
                        type=AuthenticationType.oauth2proxy
                        if isinstance(user, AuthenticatedAPIUser)
                        else AuthenticationType.token,
                        secretRef=SecretRef(name=server_name, key="auth", adopt=True),
                        extraVolumeMounts=[
                            ExtraVolumeMount(name="renku-authorized-emails", mountPath="/authorized_emails")
                        ]
                        if isinstance(user, AuthenticatedAPIUser)
                        else [],
                    ),
                ),
            )
            parsed_proxy_url = urlparse(urljoin(server.server_url + "/", "oauth2"))
            secret_data = {}
            if isinstance(user, AuthenticatedAPIUser):
                secret_data["auth"] = dumps(
                    {
                        "provider": "oidc",
                        "client_id": self.nb_config.sessions.oidc.client_id,
                        "oidc_issuer_url": self.nb_config.sessions.oidc.issuer_url,
                        "session_cookie_minimal": True,
                        "skip_provider_button": True,
                        "redirect_url": urljoin(server.server_url + "/", "oauth2/callback"),
                        "cookie_path": parsed_server_url.path,
                        "proxy_prefix": parsed_proxy_url.path,
                        "authenticated_emails_file": "/authorized_emails/authorized_emails",
                        "client_secret": self.nb_config.sessions.oidc.client_secret,
                        "cookie_secret": base64.urlsafe_b64encode(os.urandom(32)).decode(),
                        "insecure_oidc_allow_unverified_email": self.nb_config.sessions.oidc.allow_unverified_email,
                    }
                )
                secret_data["authorized_emails"] = user.email
            else:
                secret_data["auth"] = safe_dump(
                    {
                        "token": user.id,
                        "cookie_key": "Renku-Auth-Anon-Id",
                        "verbose": True,
                    }
                )
            secret = V1Secret(metadata=V1ObjectMeta(name=server_name), string_data=secret_data)
            secret = await self.nb_config.k8s_v2_client.create_secret(secret)
            try:
                manifest = await self.nb_config.k8s_v2_client.create_server(manifest, user.id)
            except Exception:
                await self.nb_config.k8s_v2_client.delete_secret(secret.metadata.name)
                raise errors.ProgrammingError(message="Could not start the amalthea session")

            return json(manifest.as_apispec().model_dump(mode="json", exclude_none=True), 201)

        return "/sessions", ["POST"], _handler

    def get_all(self) -> BlueprintFactoryResponse:
        """Get all sessions for a user."""

        @authenticate(self.authenticator)
        async def _handler(_: Request, user: AuthenticatedAPIUser | AnonymousAPIUser) -> HTTPResponse:
            sessions = await self.nb_config.k8s_v2_client.list_servers(user.id)
            output: list[dict] = []
            for session in sessions:
                output.append(session.as_apispec().model_dump(exclude_none=True, mode="json"))
            return json(output)

        return "/sessions", ["GET"], _handler

    def get_one(self) -> BlueprintFactoryResponse:
        """Get a specific session for a user."""

        @authenticate(self.authenticator)
        async def _handler(_: Request, user: AuthenticatedAPIUser | AnonymousAPIUser, session_id: str) -> HTTPResponse:
            session = await self.nb_config.k8s_v2_client.get_server(session_id, user.id)
            if session is None:
                raise errors.ValidationError(message=f"The session with ID {session_id} does not exist.", quiet=True)
            return json(session.as_apispec().model_dump(exclude_none=True, mode="json"))

        return "/sessions/<session_id>", ["GET"], _handler

    def delete(self) -> BlueprintFactoryResponse:
        """Fully delete a session with the new operator."""

        @authenticate(self.authenticator)
        async def _handler(_: Request, user: AuthenticatedAPIUser | AnonymousAPIUser, session_id: str) -> HTTPResponse:
            await self.nb_config.k8s_v2_client.delete_server(session_id, user.id)
            return empty()

        return "/sessions/<session_id>", ["DELETE"], _handler

    def patch(self) -> BlueprintFactoryResponse:
        """Patch a session."""

        @authenticate(self.authenticator)
        @validate(json=apispec.SessionPatchRequest)
        async def _handler(
            _: Request,
            user: AuthenticatedAPIUser | AnonymousAPIUser,
            session_id: str,
            body: apispec.SessionPatchRequest,
        ) -> HTTPResponse:
            session = await self.nb_config.k8s_v2_client.get_server(session_id, user.id)
            if session is None:
                raise errors.MissingResourceError(
                    message=f"The sesison with ID {session_id} does not exist", quiet=True
                )
            # TODO: Some patching should only be done when the session is in some states to avoid inadvertent restarts
            patches: dict[str, Any] = {}
            if body.resource_class_id is not None:
                rcs = await self.rp_repo.get_classes(user, id=body.resource_class_id)
                if len(rcs) == 0:
                    raise errors.MissingResourceError(
                        message=f"The resource class you requested with ID {body.resource_class_id} does not exist",
                        quiet=True,
                    )
                rc = rcs[0]
                patches |= dict(
                    spec=dict(
                        session=dict(
                            resources=dict(requests=dict(cpu=f"{round(rc.cpu * 1000)}m", memory=f"{rc.memory}Gi"))
                        )
                    )
                )
                # TODO: Add a config to specifiy the gpu kind, there is also GpuKind enum in reosurce_pools
                patches["spec"]["session"]["resources"]["requests"]["nvidia.com/gpu"] = rc.gpu
                # NOTE: K8s fails if the gpus limit is not equal to the requests because it cannot be overcommited
                patches["spec"]["session"]["resources"]["limits"] = {"nvidia.com/gpu": rc.gpu}
            if (
                body.state is not None
                and body.state.value.lower() == State.Hibernated.value.lower()
                and body.state.value.lower() != session.status.state.value.lower()
            ):
                if "spec" not in patches:
                    patches["spec"] = {}
                patches["spec"]["hibernated"] = True
            elif (
                body.state is not None
                and body.state.value.lower() == State.Running.value.lower()
                and session.status.state.value.lower() != body.state.value.lower()
            ):
                if "spec" not in patches:
                    patches["spec"] = {}
                patches["spec"]["hibernated"] = False

            if len(patches) > 0:
                new_session = await self.nb_config.k8s_v2_client.patch_server(session_id, user.id, patches)
            else:
                new_session = session

            return json(new_session.as_apispec().model_dump(exclude_none=True, mode="json"))

        return "/sessions/<session_id>", ["PATCH"], _handler

    def logs(self) -> BlueprintFactoryResponse:
        """Get logs from the session."""

        @authenticate(self.authenticator)
        @validate(query=apispec.SessionsSessionIdLogsGetParametersQuery)
        async def _handler(
            _: Request,
            user: AuthenticatedAPIUser | AnonymousAPIUser,
            session_id: str,
            query: apispec.SessionsSessionIdLogsGetParametersQuery,
        ) -> HTTPResponse:
            logs = await self.nb_config.k8s_v2_client.get_server_logs(session_id, user.id, query.max_lines)
            return json(apispec.SessionLogsResponse.model_validate(logs).model_dump_json(exclude_none=True))

        return "/sessions/<session_id>/logs", ["GET"], _handler
