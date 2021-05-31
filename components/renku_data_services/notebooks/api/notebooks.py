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
from time import sleep

from flask import Blueprint, current_app, jsonify, request, make_response
from flask_apispec import use_kwargs, doc, marshal_with
from marshmallow import fields

from .. import config
from .auth import authenticated
from .schemas import (
    LaunchNotebookRequest,
    LaunchNotebookResponse,
    ServersGetRequest,
    ServersGetResponse,
    ServerLogs,
    ServerOptionsUI,
    FailedParsing,
    AutosavesList,
)
from .classes.server import UserServer


bp = Blueprint("notebooks_blueprint", __name__, url_prefix=config.SERVICE_PREFIX)


@bp.route("servers")
@use_kwargs(ServersGetRequest(), location="query")
@marshal_with(ServersGetResponse(), code=200, description="List of all servers")
@doc(tags=["servers"], summary="Information about all active servers.")
@authenticated
def user_servers(user, **query_params):
    """Return a JSON of running servers for the user."""
    servers = [UserServer.from_pod(user, pod) for pod in user.pods]
    filter_attrs = list(filter(lambda x: x[1] is not None, query_params.items()))
    filtered_servers = {}
    for server in servers:
        if all([getattr(server, key, value) == value for key, value in filter_attrs]):
            filtered_servers[server.server_name] = server
    return {"servers": filtered_servers}


@bp.route("servers/<server_name>")
@marshal_with(LaunchNotebookResponse(), code=200, description="Server properties.")
@doc(tags=["servers"], summary="Information about an active server.")
@authenticated
def user_server(user, server_name):
    """Returns a user server based on its ID"""
    server = UserServer.from_server_name(user, server_name)
    if server is not None:
        return server
    return make_response(jsonify({"messages": {"error": "Cannot find server"}}), 404)


@bp.route("servers", methods=["POST"])
@marshal_with(
    LaunchNotebookResponse(),
    code=200,
    description="The request to create the server has been submitted.",
)
@marshal_with(
    LaunchNotebookResponse(),
    code=201,
    description="The requested server is already running.",
)
@marshal_with(
    LaunchNotebookResponse(),
    code=202,
    description="The requested server is still spawning.",
)
@marshal_with(
    LaunchNotebookResponse(),
    code=400,
    description="The requested server is in pending state.",
)
@marshal_with(FailedParsing(), code=422, description="Invalid request.")
@use_kwargs(LaunchNotebookRequest(), location="json")
@doc(tags=["servers"], summary="Start a server.")
@authenticated
def launch_notebook(
    user, namespace, project, branch, commit_sha, notebook, image, server_options
):
    server = UserServer(
        user, namespace, project, branch, commit_sha, notebook, image, server_options
    )

    if len(server.safe_username) > 63:
        return current_app.response_class(
            response=json.dumps(
                {
                    "messages": {
                        "json": {
                            "username": [
                                "A username cannot be longer than 63 characters, "
                                f"your username is {len(server.safe_username)} characters long."
                            ]
                        }
                    }
                }
            ),
            status=422,
            mimetype="application/json",
        )

    if server.server_exists():
        return server, 200

    r, error_msg = server.start()
    if error_msg is None and r.status_code == 500:
        current_app.logger.warning(
            f"Creating server {server.server_name} failed with status code 500, retrying once."
        )
        sleep(1)
        r, error_msg = server.start()

    if error_msg is not None or r is None:
        current_app.logger.error(f"server launch failed because: {error_msg}")
        return make_response(jsonify({"messages": {"error": error_msg}}), 404,)

    # check response, we expect:
    #   - HTTP 201 if the server is already running
    #   - HTTP 202 if the server is spawning
    status_code = r.status_code
    if status_code == 201:
        current_app.logger.debug(f"server {server.server_name} already running")
        return server, 201
    elif status_code == 202:
        current_app.logger.debug(f"spawn initialized for {server.server_name}")
        return server, 202
    elif status_code == 400:
        current_app.logger.debug("server in pending state")
        return server, 400
    elif status_code == 404:
        current_app.logger.debug(
            "Branch, commit, namespace, image or project does not exist"
        )
        return r
    else:
        current_app.logger.error(
            f"creating server {server.server_name} failed with {status_code}"
        )
        # unexpected status code, abort
        return make_response(
            jsonify(
                {
                    "messages": {
                        "error": f"creating server {server.server_name} failed with "
                        f"{status_code} from jupyterhub",
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
@marshal_with(FailedParsing(), code=422, description="Invalid request.")
@use_kwargs({"forced": fields.Bool(missing=False, data_key="force")}, location="query")
@authenticated
def stop_server(user, forced, server_name):
    """Stop user server with name."""
    current_app.logger.debug(
        f"Request to delete server: {server_name} forced: {forced}."
    )
    server = UserServer.from_server_name(user, server_name)
    if server is None:
        return make_response(
            jsonify({"messages": {"error": "Cannot find server"}}), 404
        )
    return server.stop(forced)


@bp.route("server_options")
@marshal_with(
    ServerOptionsUI(),
    code=200,
    description="The options shown in the UI when starting a server.",
)
@doc(tags=["servers"], summary="Get server options")
@authenticated
def server_options(user):
    """Return a set of configurable server options."""
    # TODO: append image-specific options to the options json
    return current_app.config["SERVER_OPTIONS_UI"]


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
            }
        }
    },
)
@marshal_with(ServerLogs(), code=200, description="List of server logs.")
@authenticated
def server_logs(user, server_name):
    """Return the logs of the running server."""
    server = UserServer.from_server_name(user, server_name)
    if server is not None:
        max_lines = request.args.get("max_lines", default=250, type=int)
        logs = server.get_logs(max_lines)
        if logs is not None:
            return {"items": str.splitlines(logs)}, 200
    return make_response(jsonify({"messages": {"error": "Cannot find server"}}), 404)


@bp.route("autosave/<path:namespace_group>/<string:project>")
@doc(
    tags=["autosave"],
    summary="Information about autosaved and recovered work from user sessions.",
    responses={
        200: {"description": "All the autosave branches or PVs for the project."},
        404: {"description": "The requested project and/or namespace cannot be found."},
    },
)
@marshal_with(AutosavesList(), code=200, description="List of autosaves.")
@authenticated
def autosave_info(user, namespace_group, project):
    """Information about all autosaves for a project."""
    if user.get_renku_project(f"{namespace_group}/{project}") is None:
        return make_response(
            jsonify(
                {
                    "messages": {
                        "error": f"Cannot find project {namespace_group}/{project}"
                    }
                }
            ),
            404,
        )
    return {
        "pvsSupport": current_app.config["NOTEBOOKS_SESSION_PVS_ENABLED"],
        "autosaves": user.get_autosaves(f"{namespace_group}/{project}"),
    }
