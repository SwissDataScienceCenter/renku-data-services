# -*- coding: utf-8 -*-
#
# Copyright 2019 - Swiss Data Science Center (SDSC)
# A partnership between École Polytechnique Fédérale de Lausanne (EPFL) and
# Eidgenössische Technische Hochschule Zürich (ETHZ).
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Notebooks service API."""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from flask import Blueprint, current_app, jsonify
from gitlab.const import Visibility as GitlabVisibility
from marshmallow import ValidationError, fields, validate
from webargs.flaskparser import use_args

from renku_notebooks.api.classes.user import AnonymousUser
from renku_notebooks.api.schemas.cloud_storage import RCloneStorage
from renku_notebooks.util.repository import get_status

from ..config import config
from .classes.auth import GitlabToken, RenkuTokens
from ..errors.intermittent import AnonymousUserPatchError, PVDisabledError
from ..errors.programming import ProgrammingError
from ..errors.user import MissingResourceError, UserInputError
from ..util.kubernetes_ import make_server_name
from .auth import authenticated
from .classes.image import Image
from .classes.server import UserServer
from .classes.server_manifest import UserServerManifest
from .schemas.config_server_options import ServerOptionsEndpointResponse
from .schemas.logs import ServerLogs
from .schemas.server_options import ServerOptions
from .schemas.servers_get import NotebookResponse, ServersGetRequest, ServersGetResponse
from .schemas.servers_patch import PatchServerRequest, PatchServerStatusEnum
from .schemas.servers_post import LaunchNotebookRequest
from .schemas.version import VersionResponse

bp = Blueprint("notebooks_blueprint", __name__, url_prefix=config.service_prefix)


@bp.route("/version")
def version():
    """
    Return notebook services version.

    ---
    get:
      description: Information about notebooks service.
      responses:
        200:
          description: Notebooks service info.
          content:
            application/json:
              schema: VersionResponse
    """
    info = {
        "name": "renku-notebooks",
        "versions": [
            {
                "version": config.version,
                "data": {
                    "anonymousSessionsEnabled": config.anonymous_sessions_enabled,
                    "cloudstorageEnabled": config.cloud_storage.enabled,
                    "cloudstorageClass": config.cloud_storage.storage_class,
                    "sshEnabled": config.ssh_enabled,
                },
            }
        ],
    }
    return VersionResponse().dump(info), 200


@bp.route("servers", methods=["GET"])
@use_args(ServersGetRequest(), location="query", as_kwargs=True)
@authenticated
def user_servers(user, **query_params):
    """
    Return a JSON of running servers for the user.

    ---
    get:
      description: Information about all active servers for a user.
      parameters:
        - in: query
          schema: ServersGetRequest
      responses:
        200:
          description: Map of all servers for a user.
          content:
            application/json:
              schema: ServersGetResponse
      tags:
        - servers
    """
    servers = [UserServerManifest(s) for s in config.k8s.client.list_servers(user.safe_username)]
    filter_attrs = list(filter(lambda x: x[1] is not None, query_params.items()))
    filtered_servers = {}
    ann_prefix = config.session_get_endpoint_annotations.renku_annotation_prefix
    for server in servers:
        if all(
            [server.annotations.get(f"{ann_prefix}{key}") == value for key, value in filter_attrs]
        ):
            filtered_servers[server.server_name] = server
    return ServersGetResponse().dump({"servers": filtered_servers})


@bp.route("servers/<server_name>", methods=["GET"])
@use_args({"server_name": fields.Str(required=True)}, location="view_args", as_kwargs=True)
@authenticated
def user_server(user, server_name):
    """
    Returns a user server based on its ID.

    ---
    get:
      description: Information about an active server.
      parameters:
        - in: path
          schema:
            type: string
          required: true
          name: server_name
          description: The name of the server for which additional information is required.
      responses:
        200:
          description: Server properties.
          content:
            application/json:
              schema: NotebookResponse
        404:
          description: The specified server does not exist.
          content:
            application/json:
              schema: ErrorResponse
      tags:
        - servers
    """
    server = config.k8s.client.get_server(server_name, user.safe_username)
    if server is None:
        raise MissingResourceError(message=f"The server {server_name} does not exist.")
    server = UserServerManifest(server)
    return jsonify(NotebookResponse().dump(server))


@bp.route("servers", methods=["POST"])
@use_args(LaunchNotebookRequest(), location="json", as_kwargs=True)
@authenticated
def launch_notebook(
    user,
    namespace,
    project,
    branch,
    commit_sha,
    notebook,
    image,
    resource_class_id,
    storage,
    environment_variables,
    default_url,
    lfs_auto_fetch,
    cloudstorage=None,
    server_options=None,
):
    """
    Launch a Jupyter server.

    ---
    post:
      description: Start a server.
      requestBody:
        content:
          application/json:
            schema: LaunchNotebookRequest
      responses:
        200:
          description: The server exists and is already running.
          content:
            application/json:
              schema: NotebookResponse
        201:
          description: The requested server has been created.
          content:
            application/json:
              schema: NotebookResponse
        404:
          description: The server could not be launched.
          content:
            application/json:
              schema: ErrorResponse
      tags:
        - servers
    """
    server_name = make_server_name(user.safe_username, namespace, project, branch, commit_sha)
    server = config.k8s.client.get_server(server_name, user.safe_username)
    if server:
        return NotebookResponse().dump(UserServerManifest(server)), 200

    gl_project = user.get_renku_project(f"{namespace}/{project}")
    is_image_private = False
    using_default_image = False
    image_repo = None
    if image:
        # A specific image was requested
        parsed_image = Image.from_path(image)
        image_repo = parsed_image.repo_api()
        image_exists_publicaly = image_repo.image_exists(parsed_image)
        image_exists_privately = False
        if (
            not image_exists_publicaly
            and parsed_image.hostname == config.git.registry
            and user.git_token
        ):
            image_repo = image_repo.with_oauth2_token(user.git_token)
            image_exists_privately = image_repo.image_exists(parsed_image)
        if not image_exists_privately and not image_exists_publicaly:
            using_default_image = True
            image = config.sessions.default_image
            parsed_image = Image.from_path(image)
        if image_exists_privately:
            is_image_private = True
    else:
        # An image was not requested specifically, use the one automatically built for the commit
        image = f"{config.git.registry}/{gl_project.path_with_namespace.lower()}:{commit_sha[:7]}"
        parsed_image = Image(
            config.git.registry,
            gl_project.path_with_namespace.lower(),
            commit_sha[:7],
        )
        # NOTE: a project pulled from the Gitlab API without credentials has no visibility attribute
        # and by default it can only be public since only public projects are visible to
        # non-authenticated users. Also a nice footgun from the Gitlab API Python library.
        is_image_private = (
            getattr(gl_project, "visibility", GitlabVisibility.PUBLIC) != GitlabVisibility.PUBLIC
        )
        image_repo = parsed_image.repo_api()
        if is_image_private and user.git_token:
            image_repo = image_repo.with_oauth2_token(user.git_token)
        if not image_repo.image_exists(parsed_image):
            raise MissingResourceError(
                message=(
                    f"Cannot start the session because the following the image {image} does not "
                    "exist or the user does not have the permissions to access it."
                )
            )

    parsed_server_options = None
    if resource_class_id is not None:
        # A resource class ID was passed in, validate with CRC servuce
        parsed_server_options = config.crc_validator.validate_class_storage(
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
        parsed_server_options = config.crc_validator.find_acceptable_class(
            user, requested_server_options
        )
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
        default_resource_class = config.crc_validator.get_default_class()
        max_storage_gb = default_resource_class.get("max_storage", 0)
        if storage is not None and storage > max_storage_gb:
            raise UserInputError(
                "The requested storage amount is higher than the "
                f"allowable maximum for the default resource class of {max_storage_gb}GB."
            )
        if storage is None:
            storage = default_resource_class.get("default_storage")
        parsed_server_options = ServerOptions.from_resource_class(default_resource_class)
        # Storage in request is in GB
        parsed_server_options.set_storage(storage, gigabytes=True)

    if default_url is not None:
        parsed_server_options.default_url = default_url

    if lfs_auto_fetch is not None:
        parsed_server_options.lfs_auto_fetch = lfs_auto_fetch

    image_work_dir = image_repo.image_workdir(parsed_image) or Path("/")
    mount_path = image_work_dir / "work"
    server_work_dir = image_work_dir / "work" / gl_project.path

    if cloudstorage:
        gl_project_id = gl_project.id if gl_project is not None else 0
        storages = []
        try:
            for storage in cloudstorage:
                storages.append(
                    RCloneStorage.storage_from_schema(
                        storage,
                        user=user,
                        project_id=gl_project_id,
                        work_dir=server_work_dir.absolute(),
                    )
                )
        except ValidationError as e:
            raise UserInputError(f"Couldn't load cloud storage config: {str(e)}")
        cloudstorage = storages
        mount_points = set(
            s.mount_folder for s in cloudstorage if s.mount_folder and s.mount_folder != "/"
        )
        if len(mount_points) != len(cloudstorage):
            raise UserInputError(
                "Storage mount points must be set, can't be at the root of the project and must be"
                " unique."
            )
        if any(
            s1.mount_folder.startswith(s2.mount_folder)
            for s1 in cloudstorage
            for s2 in cloudstorage
            if s1 != s2
        ):
            raise UserInputError(
                "Cannot mount a cloud storage into the mount point of another cloud storage."
            )

    server = UserServer(
        user,
        namespace,
        project,
        branch,
        commit_sha,
        notebook,
        image,
        parsed_server_options,
        environment_variables,
        cloudstorage or [],
        config.k8s.client,
        workspace_mount_path=mount_path,
        work_dir=server_work_dir,
        using_default_image=using_default_image,
        is_image_private=is_image_private,
    )

    if len(server.safe_username) > 63:
        raise UserInputError(
            message="A username cannot be longer than 63 characters, "
            f"your username is {len(server.safe_username)} characters long.",
            detail="This can occur if your username has been changed manually or by an admin.",
        )

    manifest = server.start()

    current_app.logger.debug(f"Server {server.server_name} has been started")

    return NotebookResponse().dump(UserServerManifest(manifest)), 201


@bp.route("servers/<server_name>", methods=["PATCH"])
@use_args({"server_name": fields.Str(required=True)}, location="view_args", as_kwargs=True)
@use_args(PatchServerRequest(), location="json", arg_name="patch_body")
@authenticated
def patch_server(user, server_name, patch_body):
    """
    Patch a user server by name based on the query param.

    ---
    patch:
      description: Patch a running server by name.
      requestBody:
        content:
          application/json:
            schema: PatchServerRequest
      parameters:
        - in: path
          schema:
            type: string
          name: server_name
          required: true
          description: The name of the server that should be patched.
      responses:
        200:
          description: The server was patched successfully.
          content:
            application/json:
              schema: NotebookResponse
        400:
          description: Invalid json argument value.
          content:
            application/json:
              schema: ErrorResponse
        404:
          description: The server cannot be found.
          content:
            application/json:
              schema: ErrorResponse
        500:
          description: The server exists but could not be successfully hibernated.
          content:
            application/json:
              schema: ErrorResponse
      tags:
        - servers
    """
    if not config.sessions.storage.pvs_enabled:
        raise PVDisabledError()

    if isinstance(user, AnonymousUser):
        raise AnonymousUserPatchError()

    server = config.k8s.client.get_server(server_name, user.safe_username)
    new_server = server
    currently_hibernated = server.get("spec", {}).get("jupyterServer", {}).get("hibernated", False)
    currently_failing = server.get("status", {}).get("state", "running") == "failed"
    state = patch_body.get("state")
    resource_class_id = patch_body.get("resource_class_id")
    if server and not (currently_hibernated or currently_failing) and resource_class_id:
        raise UserInputError(
            "The resource class can be changed only if the server is hibernated or failing"
        )

    if resource_class_id:
        parsed_server_options = config.crc_validator.validate_class_storage(
            user, resource_class_id, storage=None  # we do not care about validating storage
        )
        js_patch = [
            {
                "op": "replace",
                "path": "/spec/jupyterServer/resources",
                "value": parsed_server_options.to_k8s_resources(config.sessions.enforce_cpu_limits),
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
        elif server.get("metadata", {}).get("labels", {}).get("renku.io/quota"):
            js_patch.append(
                {
                    "op": "remove",
                    # NOTE: ~1 is how you escape '/' in json-patch
                    "path": "/metadata/labels/renku.io~1quota",
                }
            )
        new_server = config.k8s.client.patch_server(
            server_name=server_name, safe_username=user.safe_username, patch=js_patch
        )
        ss_patch = [
            {
                "op": "replace",
                "path": "/spec/template/spec/priorityClassName",
                "value": parsed_server_options.priority_class,
            }
        ]
        config.k8s.client.patch_statefulset(server_name=server_name, patch=ss_patch)

    if state == PatchServerStatusEnum.Hibernated.value:
        # NOTE: Do nothing if server is already hibernated
        currently_hibernated = (
            server.get("spec", {}).get("jupyterServer", {}).get("hibernated", False)
        )
        if server and currently_hibernated:
            logging.warning(f"Server {server_name} is already hibernated.")

            return NotebookResponse().dump(UserServerManifest(server)), 200

        hibernation = {"branch": "", "commit": "", "dirty": "", "synchronized": ""}

        status = get_status(server_name=server_name, access_token=user.access_token)
        if status:
            hibernation = {
                "branch": status.get("branch", ""),
                "commit": status.get("commit", ""),
                "dirty": not status.get("clean", True),
                "synchronized": status.get("ahead", 0) == status.get("behind", 0) == 0,
            }

        hibernation["date"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

        patch = {
            "metadata": {
                "annotations": {
                    "renku.io/hibernation": json.dumps(hibernation),
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

        new_server = config.k8s.client.patch_server(
            server_name=server_name, safe_username=user.safe_username, patch=patch
        )
    elif state == PatchServerStatusEnum.Running.value:
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
        renku_tokens = RenkuTokens(access_token=user.access_token, refresh_token=user.refresh_token)
        gitlab_token = GitlabToken(
            access_token=user.git_token, expires_at=user.git_token_expires_at
        )
        config.k8s.client.patch_tokens(server_name, renku_tokens, gitlab_token)
        new_server = config.k8s.client.patch_server(
            server_name=server_name, safe_username=user.safe_username, patch=patch
        )

    return NotebookResponse().dump(UserServerManifest(new_server)), 200


@bp.route("servers/<server_name>", methods=["DELETE"])
@use_args({"server_name": fields.Str(required=True)}, location="view_args", as_kwargs=True)
@use_args({"forced": fields.Boolean(load_default=False)}, location="query", as_kwargs=True)
@authenticated
def stop_server(user, forced, server_name):
    """
    Stop user server by name.

    ---
    delete:
      description: Stop a running server by name.
      parameters:
        - in: path
          schema:
            type: string
          name: server_name
          required: true
          description: The name of the server that should be deleted.
        - in: query
          schema:
            type: boolean
            default: false
          name: forced
          required: false
          description: |
            If true, delete immediately disregarding the grace period
            of the underlying JupyterServer resource.
      responses:
        204:
          description: The server was stopped successfully.
        404:
          description: The server cannot be found.
          content:
            application/json:
              schema: ErrorResponse
        500:
          description: The server exists but could not be successfully deleted.
          content:
            application/json:
              schema: ErrorResponse
      tags:
        - servers
    """
    config.k8s.client.delete_server(server_name, forced=forced, safe_username=user.safe_username)
    return "", 204


@bp.route("server_options", methods=["GET"])
@authenticated
def server_options(user):
    """
    Return a set of configurable server options.

    ---
    get:
      description: Get the options available to customize when starting a server.
      responses:
        200:
          description: Server options such as CPU, memory, storage, etc.
          content:
            application/json:
              schema: ServerOptionsEndpointResponse
      tags:
        - servers
    """
    # TODO: append image-specific options to the options json
    return ServerOptionsEndpointResponse().dump(
        {
            **config.server_options.ui_choices,
            "cloudstorage": {
                "enabled": config.cloud_storage.enabled,
            },
        },
    )


@bp.route("logs/<server_name>", methods=["GET"])
@use_args(
    {
        "max_lines": fields.Integer(
            load_default=250,
            validate=validate.Range(min=0, max=None, min_inclusive=True),
        )
    },
    as_kwargs=True,
    location="query",
)
@use_args(
    {
        "server_name": fields.Str(required=True),
    },
    location="view_args",
    as_kwargs=True,
)
@authenticated
def server_logs(user, max_lines, server_name):
    """
    Return the logs of the running server.

    ---
    get:
      description: Server logs.
      parameters:
        - in: path
          schema:
            type: string
          required: true
          name: server_name
          description: The name of the server whose logs should be fetched.
        - in: query
          schema:
            type: integer
            default: 250
            minimum: 0
          name: max_lines
          required: false
          description: |
            The maximum number of (most recent) lines to return from the logs.
      responses:
        200:
          description: Server logs. An array of strings where each element is a line of the logs.
          content:
            application/json:
              schema: ServerLogs
        404:
          description: The specified server does not exist.
          content:
            application/json:
              schema: ErrorResponse
      tags:
        - logs
    """
    logs = config.k8s.client.get_server_logs(
        server_name=server_name,
        max_log_lines=max_lines,
        safe_username=user.safe_username,
    )
    return jsonify(ServerLogs().dump(logs))


@bp.route("images", methods=["GET"])
@use_args({"image_url": fields.String(required=True)}, as_kwargs=True, location="query")
@authenticated
def check_docker_image(user, image_url):
    """
    Return the availability of the docker image.

    ---
    get:
      description: Docker image availability.
      parameters:
        - in: query
          schema:
            type: string
          required: true
          name: image_url
          description: The Docker image URL (tag included) that should be fetched.
      responses:
        200:
          description: The Docker image is available.
        404:
          description: The Docker image is not available.
      tags:
        - images
    """
    parsed_image = Image.from_path(image_url)
    image_repo = parsed_image.repo_api()
    if parsed_image.hostname == config.git.registry and user.git_token:
        image_repo = image_repo.with_oauth2_token(user.git_token)
    if image_repo.image_exists(parsed_image):
        return "", 200
    else:
        return "", 404
