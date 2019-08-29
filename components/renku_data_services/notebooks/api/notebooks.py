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

from flask import Blueprint, abort, current_app, jsonify, request, make_response

from .. import config
from ..util.gitlab_ import (
    get_notebook_image,
    get_project,
    check_user_has_developer_permission,
)
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
)
from .auth import authenticated


bp = Blueprint("notebooks_blueprint", __name__, url_prefix=config.SERVICE_PREFIX)


@bp.route("servers")
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
@authenticated
def user_server(user, server_name):
    """Returns a user server based on its ID"""
    server = get_user_server(user, server_name)
    return jsonify(server)


@bp.route("servers", methods=["POST"])
@authenticated
def launch_notebook(user):
    """Launch user server with a given arguments."""
    try:
        payload = request.json
        namespace = payload["namespace"]
        project = payload["project"]
        branch = payload.get("branch", "master")
        commit_sha = payload["commit_sha"]
        notebook = payload.get("notebook")
    except (AttributeError, KeyError):
        return current_app.response_class(
            status=400,
            response="Invalid payload. 'namespace', 'project', and 'commit_sha' are mandatory.",
        )

    # 0. check if server already exists and if so return it
    server_name = make_server_name(namespace, project, branch, commit_sha)

    current_app.logger.debug(
        f"Request to create server: {server_name} with options: {payload} for user: {user}"
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
    server_options_defaults = _read_server_options_file()

    # process the requested options and set others to defaults from config
    server_options = (request.get_json() or {}).get("serverOptions", {})
    server_options.setdefault(
        "defaultUrl",
        server_options_defaults.pop("defaultUrl", {}).get(
            "default", os.getenv("JUPYTERHUB_SINGLEUSER_DEFAULT_URL")
        ),
    )

    for key in server_options_defaults.keys():
        server_options.setdefault(key, server_options_defaults.get(key)["default"])

    gl_project = get_project(user, namespace, project)

    if gl_project is None:
        return current_app.response_class(
            status=404,
            response=f"Cannot find project {project} for user: {user['name']}.",
        )

    # Return 401 if user is not a developer
    if not check_user_has_developer_permission(user, gl_project):
        return current_app.response_class(
            status=401,
            response="Not authorized to use interactive environments for this project.",
        )

    # set the notebook image
    image = get_notebook_image(user, namespace, project, commit_sha)

    payload = {
        "namespace": namespace,
        "project": project,
        "branch": branch,
        "commit_sha": commit_sha,
        "project_id": gl_project.id,
        "notebook": notebook,
        "image": image,
        "git_clone_image": os.getenv("GIT_CLONE_IMAGE", "renku/git-clone:latest"),
        "server_options": server_options,
    }

    current_app.logger.debug(f"Creating server {server_name} with {payload}")

    if os.environ.get("GITLAB_REGISTRY_SECRET"):
        payload["image_pull_secrets"] = payload.get("image_pull_secrets", [])
        payload["image_pull_secrets"].append(os.environ["GITLAB_REGISTRY_SECRET"])

    r = create_named_server(user, server_name, payload)

    # 2. check response, we expect:
    #   - HTTP 201 if the server is already running; in this case redirect to it
    #   - HTTP 202 if the server is spawning
    if r.status_code == 201:
        current_app.logger.debug(f"server {server_name} already running")
    elif r.status_code == 202:
        current_app.logger.debug(f"spawn initialized for {server_name}")
    elif r.status_code == 400:
        current_app.logger.debug("server in pending state")
    else:
        current_app.logger.error(
            f"creating server {server_name} failed with {r.status_code}"
        )
        # unexpected status code, abort
        abort(r.status_code)

    # fetch the server
    server = get_user_server(user, server_name)
    return current_app.response_class(
        response=json.dumps(server), status=r.status_code, mimetype="application/json"
    )


@bp.route("servers/<server_name>", methods=["DELETE"])
@authenticated
def stop_server(user, server_name):
    """Stop user server with name."""
    forced = request.args.get("force", "").lower() == "true"

    current_app.logger.debug(
        f"Request to delete server: {server_name} forced: {forced} for user: {user}"
    )

    if forced:
        server = get_user_server(user, server_name)
        if server:
            pod_name = server.get("state", {}).get("pod_name", "")
            if delete_user_pod(user, pod_name):
                return make_response("", 204)
            else:
                return make_response("Cannot force delete server", 400)
        return make_response("", 404)

    r = delete_named_server(user, server_name)
    return current_app.response_class(r.content, status=r.status_code)


@bp.route("server_options")
@authenticated
def server_options(user):
    """Return a set of configurable server options."""
    server_options = _read_server_options_file()

    # TODO: append image-specific options to the options json
    return jsonify(server_options)


@bp.route("logs/<server_name>")
@authenticated
def server_logs(user, server_name):
    """"Return the logs of the running server."""
    if request.environ["HTTP_ACCEPT"] == "application/json":
        return make_response("Only supporting text/plain.", 406)
    server = get_user_server(user, server_name)
    if server:
        pod_name = server.get("state", {}).get("pod_name", "")
        logs = read_namespaced_pod_log(pod_name)
        response = make_response(logs, 200)
    else:
        response = make_response("", 404)
    response.mimetype = "text/plain"
    return response


def _read_server_options_file():
    server_options_file = os.getenv(
        "NOTEBOOKS_SERVER_OPTIONS_PATH", "/etc/renku-notebooks/server_options.json"
    )
    with open(server_options_file) as f:
        server_options = json.load(f)
    return server_options
