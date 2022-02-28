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
from webargs import fields
from webargs.flaskparser import use_args

from .. import config
from .auth import authenticated
from .schemas import (
    AutosavesList,
    ServerOptionsUI,
    LaunchNotebookRequest,
    LaunchNotebookResponse,
    ServersGetRequest,
    ServersGetResponse,
    ServerLogs,
    VersionResponse,
)
from .classes.server import UserServer
from .classes.storage import Autosave


bp = Blueprint("notebooks_blueprint", __name__, url_prefix=config.SERVICE_PREFIX)


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
                "version": config.NOTEBOOKS_SERVICE_VERSION,
                "data": {
                    "anonymousSessionsEnabled": config.ANONYMOUS_SESSIONS_ENABLED,
                    "cloudstorageEnabled": {
                        "s3": config.S3_MOUNTS_ENABLED,
                    },
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
    servers = [UserServer.from_js(user, js) for js in user.jss]
    filter_attrs = list(filter(lambda x: x[1] is not None, query_params.items()))
    filtered_servers = {}
    for server in servers:
        if all([getattr(server, key, value) == value for key, value in filter_attrs]):
            filtered_servers[server.server_name] = server
    return ServersGetResponse().dump({"servers": filtered_servers})


@bp.route("servers/<server_name>", methods=["GET"])
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
              schema: LaunchNotebookResponse
        404:
          description: The specified server does not exist.
      tags:
        - servers
    """
    server = UserServer.from_server_name(user, server_name)
    if server is not None:
        return LaunchNotebookResponse().dump(server)
    return make_response(jsonify({"messages": {"error": "Cannot find server"}}), 404)


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
    server_options,
    cloudstorage=[],
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
              schema: LaunchNotebookResponse
        201:
          description: The requested server has been created.
          content:
            application/json:
              schema: LaunchNotebookResponse
        404:
          description: The server could not be launched.
      tags:
        - servers
    """
    server = UserServer(
        user,
        namespace,
        project,
        branch,
        commit_sha,
        notebook,
        image,
        server_options,
        cloudstorage,
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
        return LaunchNotebookResponse().dump(server)

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
    return LaunchNotebookResponse().dump(server), 201


@bp.route("servers/<server_name>", methods=["DELETE"])
@use_args({"forced": fields.Boolean(missing=False)}, as_kwargs=True)
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
        500:
          description: The server exists but could not be successfully deleted.
      tags:
        - servers
    """
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
              schema: ServerOptionsUI
      tags:
        - servers
    """
    # TODO: append image-specific options to the options json
    return ServerOptionsUI().dump(
        {
            **current_app.config["SERVER_OPTIONS_UI"],
            # TODO: enable when the UI supports fully s3 buckets
            # currently passing this breaks the sessions settings page
            # "cloudstorage": {
            #     "s3": {"enabled": current_app.config["S3_MOUNTS_ENABLED"]}
            # },
        },
    )


@bp.route("logs/<server_name>", methods=["GET"])
@authenticated
def server_logs(user, server_name):
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
      responses:
        200:
          description: Server logs. An array of strings where each element is a line of the logs.
          content:
            application/json:
              schema: ServerLogs
              example:
                - Line 1 of logs
                - Line 2 of logs
        404:
          description: The specified server does not exist.
      tags:
        - logs
    """
    server = UserServer.from_server_name(user, server_name)
    if server is not None:
        max_lines = request.args.get("max_lines", default=250, type=int)
        logs = server.get_logs(max_lines)
        if logs is not None:
            return (
                ServerLogs().dumps({"items": str.splitlines(logs)}),
                200,
            )
    return make_response(jsonify({"messages": {"error": "Cannot find server"}}), 404)


@bp.route("<path:namespace_project>/autosave", methods=["GET"])
@authenticated
def autosave_info(user, namespace_project):
    """
    Information about all autosaves for a project.

    ---
    get:
      description: Information about autosaved and recovered work from user sessions.
      parameters:
        - in: path
          name: namespace_project
          schema:
            type: string
          required: true
          description: |
            URL encoded namespace and project in the format of `namespace/project`.
            However since this should be URL encoded what should actually be used
            in the request is `namespace%2Fproject`.
      responses:
        200:
          description: All the autosave branches or PVs for the project
          content:
            application/json:
              schema: AutosavesList
        404:
          description: The requested project and/or namespace cannot be found
      tags:
        - autosave
    """
    if user.get_renku_project(namespace_project) is None:
        return make_response(
            jsonify(
                {"messages": {"error": f"Cannot find project {namespace_project}"}}
            ),
            404,
        )
    return AutosavesList().dump(
        {
            "pvsSupport": current_app.config["NOTEBOOKS_SESSION_PVS_ENABLED"],
            "autosaves": user.get_autosaves(namespace_project),
        },
    )


@bp.route(
    "<path:namespace_project>/autosave/<path:autosave_name>",
    methods=["DELETE"],
)
@authenticated
def delete_autosave(user, namespace_project, autosave_name):
    """
    Delete an autosave PV and or branch.

    ---
    delete:
      description: Stop a running server by name.
      parameters:
        - in: path
          schema:
            type: string
          name: namespace_project
          required: true
          description: |
            URL encoded namespace and project in the format of `namespace/project`.
            However since this should be URL encoded what should actually be used
            in the request is `namespace%2Fproject`.
        - in: path
          schema:
            type: string
          name: autosave_name
          required: true
          description: |
            URL encoded name of the autosave as returned by the
            /<namespace_project>/autosave endpoint.
      responses:
        204:
          description: The autosave branch and/or PV has been deleted successfully.
        404:
          description: The requested project, namespace and/or autosave cannot be found.
      tags:
        - autosave
    """
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
