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
    LaunchNotebookRequestWithS3,
    LaunchNotebookRequestWithoutS3,
    LaunchNotebookResponseWithS3,
    LaunchNotebookResponseWithoutS3,
    ServersGetRequest,
    ServersGetResponse,
    ServerLogs,
    ServerOptionsUI,
    FailedParsing,
    AutosavesList,
)
from .classes.server import UserServer
from .classes.storage import Autosave


bp = Blueprint("notebooks_blueprint", __name__, url_prefix=config.SERVICE_PREFIX)


@bp.route("servers", methods=["GET"])
@use_kwargs(ServersGetRequest(), location="query")
@marshal_with(ServersGetResponse(), code=200, description="List of all servers")
@doc(tags=["servers"], summary="Information about all active servers.")
@authenticated
def user_servers(user, **query_params):
    """Return a JSON of running servers for the user."""
    servers = [UserServer.from_js(user, js) for js in user.jss]
    filter_attrs = list(filter(lambda x: x[1] is not None, query_params.items()))
    filtered_servers = {}
    for server in servers:
        if all([getattr(server, key, value) == value for key, value in filter_attrs]):
            filtered_servers[server.server_name] = server
    return {"servers": filtered_servers}


@bp.route("servers/<server_name>", methods=["GET"])
@marshal_with(
    (
        LaunchNotebookResponseWithS3()
        if config.S3_MOUNTS_ENABLED
        else LaunchNotebookResponseWithoutS3()
    ),
    code=200,
    description="Server properties.",
)
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
    (
        LaunchNotebookResponseWithS3()
        if config.S3_MOUNTS_ENABLED
        else LaunchNotebookResponseWithoutS3()
    ),
    code=200,
    description="The server exists and is already running.",
)
@marshal_with(
    (
        LaunchNotebookResponseWithS3()
        if config.S3_MOUNTS_ENABLED
        else LaunchNotebookResponseWithoutS3()
    ),
    code=201,
    description="The requested server has been created.",
)
@marshal_with(FailedParsing(), code=422, description="Invalid request.")
@use_kwargs(
    LaunchNotebookRequestWithS3()
    if config.S3_MOUNTS_ENABLED
    else LaunchNotebookRequestWithoutS3(),
    location="json",
)
@doc(
    tags=["servers"],
    summary="Start a server.",
    responses={404: {"description": "The server could not be launched."}},
)
@authenticated
def launch_notebook(
    user,
    namespace,
    project,
    branch,
    commit_sha,
    notebook,
    image,
    server_options,
    s3mounts=[],
):
    server = UserServer(
        user,
        namespace,
        project,
        branch,
        commit_sha,
        notebook,
        image,
        server_options,
        s3mounts,
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

    server.get_js()
    if server.server_exists():
        return server, 200

    js, error = server.start()
    if js is None:
        current_app.logger.warning(
            f"Creating server {server.server_name} failed, retrying once."
        )
        sleep(1)
        js, error = server.start()
        if js is None:
            current_app.logger.error(
                f"Server {server.server_name} launch failed on retry."
            )
            return make_response(
                jsonify(
                    {
                        "messages": {
                            "error": f"Cannot start server {server.server_name}, because {error}"
                        }
                    }
                ),
                404,
            )

    current_app.logger.debug(f"Server {server.server_name} has been started")
    for autosave in user.get_autosaves(server.gl_project.path_with_namespace):
        autosave.cleanup(server.commit_sha)
    return server, 201


@bp.route("servers/<server_name>", methods=["DELETE"])
@doc(
    tags=["servers"],
    summary="Stop a running server.",
    responses={
        204: {"description": "The server was stopped."},
        404: {"description": "The server cannot be found."},
        500: {
            "description": "The server exists but could not be successfully deleted."
        },
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
            jsonify({"messages": {"error": f"Cannot find server {server_name}"}}), 404
        )
    else:
        status = server.stop(forced)
        if status is not None:
            return "", 204
        else:
            return make_response(
                jsonify(
                    {"messages": {"error": f"Cannot delete the server {server_name}"}}
                ),
                500,
            )


@bp.route("server_options", methods=["GET"])
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
    return {
        **current_app.config["SERVER_OPTIONS_UI"],
        "s3mounts": {"enabled": current_app.config["S3_MOUNTS_ENABLED"]},
    }


@bp.route("logs/<server_name>", methods=["GET"])
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


@bp.route("<path:namespace_project>/autosave", methods=["GET"])
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
def autosave_info(user, namespace_project):
    """Information about all autosaves for a project."""
    if user.get_renku_project(namespace_project) is None:
        return make_response(
            jsonify(
                {"messages": {"error": f"Cannot find project {namespace_project}"}}
            ),
            404,
        )
    return {
        "pvsSupport": current_app.config["NOTEBOOKS_SESSION_PVS_ENABLED"],
        "autosaves": user.get_autosaves(namespace_project),
    }


@bp.route(
    "<path:namespace_project>/autosave/<path:autosave_name>",
    methods=["DELETE"],
)
@doc(
    tags=["autosave"],
    summary="Delete an autosave PV and or branch.",
    responses={
        204: {"description": "The autosave branch and/or PV has been deleted."},
        404: {
            "description": "The requested project, namespace and/or autosave cannot be found."
        },
    },
)
@authenticated
def delete_autosave(user, namespace_project, autosave_name):
    """Delete an autosave PV and or branch."""
    if user.get_renku_project(namespace_project) is None:
        return make_response(
            jsonify(
                {"messages": {"error": f"Cannot find project {namespace_project}"}}
            ),
            404,
        )
    autosave = Autosave.from_name(user, namespace_project, autosave_name)
    if not autosave.exists:
        return make_response(
            jsonify(
                {"messages": {"error": f"The autosave {autosave_name} does not exist"}}
            ),
            404,
        )
    autosave.delete()
    return make_response("", 204)
