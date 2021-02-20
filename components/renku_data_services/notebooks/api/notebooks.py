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
import os
from urllib.parse import urlparse
from uuid import uuid4
from time import sleep

import escapism
from flask import Blueprint, current_app, jsonify, request, make_response
from flask_apispec import use_kwargs, doc
from kubernetes.client.rest import ApiException
from marshmallow import fields

from .. import config
from ..util.check_image import get_docker_token, image_exists, parse_image_name
from ..util.gitlab_ import get_renku_project
from ..util.jupyterhub_ import (
    make_server_name,
    create_named_server,
    delete_named_server,
    check_user_has_named_server,
)
from ..util.kubernetes_ import (
    read_namespaced_pod_log,
    get_user_server,
    get_user_servers,
    delete_user_pod,
    create_registry_secret,
)
from .auth import authenticated
from .decorators import validate_response_with
from .schemas import (
    LaunchNotebookRequest,
    LaunchNotebookResponse,
    ServersGetResponse,
    ServerLogs,
    ServerOptions,
    FailedParsing,
)
from ..util.misc import read_server_options_file


bp = Blueprint("notebooks_blueprint", __name__, url_prefix=config.SERVICE_PREFIX)


@bp.route("servers")
@validate_response_with(
    {200: {"schema": ServersGetResponse(), "description": "List of all servers."}}
)
@doc(tags=["servers"], summary="Information about all active servers.")
@authenticated
def user_servers(user):
    """Return a JSON of running servers for the user."""
    namespace = request.args.get("namespace")
    project = request.args.get("project")
    branch = request.args.get("branch")
    commit_sha = request.args.get("commit_sha")

    servers = get_user_servers(user, namespace, project, branch, commit_sha)
    current_app.logger.debug(servers)
    return jsonify({"servers": servers})


@bp.route("servers/<server_name>")
@validate_response_with(
    {200: {"schema": LaunchNotebookResponse(), "description": "Server properties."}}
)
@doc(tags=["servers"], summary="Information about an active server.")
@authenticated
def user_server(user, server_name):
    """Returns a user server based on its ID"""
    server = get_user_server(user, server_name)
    return jsonify(server)


@bp.route("servers", methods=["POST"])
@validate_response_with(
    {
        200: {
            "schema": LaunchNotebookResponse(),
            "description": "The request to create the server has been submitted.",
        },
        201: {
            "schema": LaunchNotebookResponse(),
            "description": "The requested server is already running.",
        },
        202: {
            "schema": LaunchNotebookResponse(),
            "description": "The requested server is still spawning.",
        },
        400: {
            "schema": LaunchNotebookResponse(),
            "description": "The requested server is in pending state.",
        },
        422: {"schema": FailedParsing(), "description": "Invalid request."},
    }
)
@use_kwargs(LaunchNotebookRequest(), location="json")
@doc(tags=["servers"], summary="Start a server.")
@authenticated
def launch_notebook(
    user, namespace, project, branch, commit_sha, notebook, image, server_options
):
    """Launch user server with a given arguments."""
    # 0. check if server already exists and if so return it
    server_name = make_server_name(namespace, project, branch, commit_sha)
    safe_username = escapism.escape(user.get("name"), escape_char="-").lower()

    if len(safe_username) > 63:
        return current_app.response_class(
            response=json.dumps(
                {
                    "messages": {
                        "json": {
                            "username": [
                                "A username cannot be longer than 63 characters, "
                                f"your username is {len(safe_username)} characters long."
                            ]
                        }
                    }
                }
            ),
            status=422,
            mimetype="application/json",
        )

    current_app.logger.debug(
        f"Request to create server: {server_name} with namespace: {namespace}, "
        f"project: {project}, branch: {branch}, commit_sha:{commit_sha}, "
        f"notebook: {notebook}, image: {image} for user: {user}"
    )

    if check_user_has_named_server(user, server_name):
        server = get_user_server(user, server_name)
        current_app.logger.debug(
            f"Server {server_name} already exists in JupyterHub: {server}"
        )
        return current_app.response_class(
            response=json.dumps(server), status=200, mimetype="application/json"
        )

    # 1. launch using spawner that checks the access

    # process the server options
    # server options from system configuration
    server_options_defaults = read_server_options_file()

    # process the requested options and set others to defaults from config
    server_options.setdefault(
        "defaultUrl",
        server_options_defaults.pop("defaultUrl", {}).get(
            "default", os.getenv("JUPYTERHUB_SINGLEUSER_DEFAULT_URL")
        ),
    )

    for key in server_options_defaults.keys():
        server_options.setdefault(key, server_options_defaults.get(key)["default"])

    gl_project = get_renku_project(user, f"{namespace}/{project}")

    if gl_project is None:
        return make_response(
            jsonify(
                {
                    "messages": {
                        "error": f"Cannot find project {project} for user: {user['name']}."
                    }
                }
            ),
            404,
        )

    # set the notebook image if not specified in the request
    if image is None:
        parsed_image = {
            "hostname": config.IMAGE_REGISTRY,
            "image": gl_project.path_with_namespace.lower(),
            "tag": commit_sha[:7],
        }
        commit_image = (
            f"{config.IMAGE_REGISTRY}/{gl_project.path_with_namespace.lower()}"
            f":{commit_sha[:7]}"
        )
    else:
        parsed_image = parse_image_name(image)
    # get token
    token, is_image_private = get_docker_token(**parsed_image, user=user)
    # check if images exist
    image_exists_result = image_exists(**parsed_image, token=token)
    # assign image
    if image_exists_result and image is None:
        # the image tied to the commit exists
        verified_image = commit_image
    elif not image_exists_result and image is None:
        # the image tied to the commit does not exist, fallback to default image
        verified_image = config.DEFAULT_IMAGE
        is_image_private = False
        current_app.logger.debug(
            f"Image for the selected commit {commit_sha} of {project}"
            f" not found, using default image {config.DEFAULT_IMAGE}"
        )
    elif image_exists_result and image is not None:
        # a specific image was requested and it exists
        verified_image = image
    else:
        # a specific image was requested but does not exist
        return make_response(
            jsonify({"messages": {"error": f"Cannot find/access image {image}."}}), 404
        )

    payload = {
        "namespace": namespace,
        "project": project,
        "branch": branch,
        "commit_sha": commit_sha,
        "project_id": gl_project.id,
        "notebook": notebook,
        "image": verified_image,
        "git_clone_image": os.getenv("GIT_CLONE_IMAGE", "renku/git-clone:latest"),
        "git_https_proxy_image": os.getenv(
            "GIT_HTTPS_PROXY_IMAGE", "renku/git-https-proxy:latest"
        ),
        "server_options": server_options,
    }

    current_app.logger.debug(f"Creating server {server_name} with {payload}")

    # only create a pull secret if the project has limited visibility and a token is available
    if config.GITLAB_AUTH and is_image_private:
        git_host = urlparse(config.GITLAB_URL).netloc
        secret_name = f"{safe_username}-registry-{str(uuid4())}"
        create_registry_secret(
            user, namespace, secret_name, gl_project.id, commit_sha, git_host
        )
        payload["image_pull_secrets"] = [secret_name]

    r = create_named_server(user, server_name, payload)
    server = get_user_server(user, server_name)

    if r.status_code == 500:
        current_app.logger.warning(
            f"Creating server {server_name} failed with status code 500, retrying once."
        )
        sleep(1)
        r = create_named_server(user, server_name, payload)
        server = get_user_server(user, server_name)

    # 2. check response, we expect:
    #   - HTTP 201 if the server is already running
    #   - HTTP 202 if the server is spawning
    if r.status_code == 201:
        current_app.logger.debug(f"server {server_name} already running")
        return current_app.response_class(
            response=json.dumps(server), status=201, mimetype="application/json"
        )
    elif r.status_code == 202:
        current_app.logger.debug(f"spawn initialized for {server_name}")
        return current_app.response_class(
            response=json.dumps(server), status=202, mimetype="application/json"
        )
    elif r.status_code == 400:
        current_app.logger.debug("server in pending state")
        return current_app.response_class(
            response=json.dumps(server), status=400, mimetype="application/json"
        )
    else:
        current_app.logger.error(
            f"creating server {server_name} failed with {r.status_code}"
        )
        # unexpected status code, abort
        return make_response(
            jsonify(
                {
                    "messages": {
                        "error": f"creating server {server_name} failed with "
                        f"{r.status_code} from jupyterhub",
                    }
                }
            ),
            500,
        )


@bp.route("servers/<server_name>", methods=["DELETE"])
@doc(
    tags=["servers"],
    summary="Stop a running server.",
    responses={
        204: {"description": "The server was stopped."},
        202: {
            "description": "The server was not stopped, it is taking a while to stop."
        },
        400: {
            "description": "Only for 'force-delete', cannot force delete the server."
        },
        404: {"description": "The server cannot be found."},
    },
)
@validate_response_with(
    {422: {"schema": FailedParsing(), "description": "Invalid request."}}
)
@use_kwargs({"forced": fields.Bool(missing=False, data_key="force")}, location="query")
@authenticated
def stop_server(user, forced, server_name):
    """Stop user server with name."""
    current_app.logger.debug(
        f"Request to delete server: {server_name} forced: {forced} for user: {user}"
    )

    if forced:
        server = get_user_server(user, server_name)
        if server:
            pod_name = server.get("state", {}).get("pod_name", "")
            if delete_user_pod(user, pod_name):
                return "", 204
            else:
                return make_response(
                    jsonify({"messages": {"error": "Cannot force delete server"}}), 400
                )
        return make_response(jsonify({"messages": {"error": "Server not found."}}), 404)

    r = delete_named_server(user, server_name)
    if r.status_code == 204:
        return "", 204
    elif r.status_code == 202:
        return make_response(
            jsonify(
                {
                    "messages": {
                        "information": "The server was not stopped, it is taking a while to stop."
                    }
                }
            ),
            r.status_code,
        )
    else:
        message = r.json().get(
            "message", "Something went wrong while tring to stop the server"
        )
        return make_response(jsonify({"messages": {"error": message}}), r.status_code)


@bp.route("server_options")
@validate_response_with(
    {
        200: {
            "schema": ServerOptions(),
            "description": "The options available when starting a server.",
        }
    }
)
@doc(tags=["servers"], summary="Get server options")
@authenticated
def server_options(user):
    """Return a set of configurable server options."""
    server_options = read_server_options_file()

    # TODO: append image-specific options to the options json
    return jsonify(server_options)


@bp.route("logs/<server_name>")
@doc(
    tags=["logs"],
    summary="Get server logs",
    # marshmallow does not allow arrays at top level
    # this is a way to bypass that in the docs
    responses={
        200: {
            "examples": {
                "application/json": ["Line 1 of logs", "Line 2 of logs"],
                "text/plain": ["Line 1 of logs", "Line 2 of logs"],
            },
        }
    },
)
@validate_response_with(
    {200: {"schema": ServerLogs(), "description": "List of server logs."}}
)
@authenticated
def server_logs(user, server_name):
    """Return the logs of the running server."""
    server = get_user_server(user, server_name)
    if server:
        pod_name = server.get("state", {}).get("pod_name", "")
        try:
            max_lines = request.args.get("max_lines", default=250, type=int)
            logs = read_namespaced_pod_log(pod_name, max_lines)
        # catch predictable k8s api errors and return a significative string
        except ApiException as e:
            logs = ""
            if hasattr(e, "body"):
                k8s_error = json.loads(e.body)
                logs = f"Logs unavailable: {k8s_error['message']}"
        response = jsonify({"items": str.splitlines(logs)})
    else:
        response = make_response(
            jsonify({"messages": {"error": "Cannot find server"}}), 404
        )
    return response
