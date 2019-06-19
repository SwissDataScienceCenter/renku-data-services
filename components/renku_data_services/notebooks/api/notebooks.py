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

import requests
from flask import Blueprint, abort, current_app, jsonify, request, make_response

from .. import config
from ..util.gitlab_ import (
    get_notebook_image,
    get_project,
    check_user_has_developer_permission,
)
from ..util.jupyterhub_ import get_user_server, server_name
from ..util.kubernetes_ import annotate_servers, read_namespaced_pod_log
from .auth import auth, authenticated, get_user_info

bp = Blueprint("notebooks_blueprint", __name__, url_prefix=config.SERVICE_PREFIX)

SERVER_STATUS_MAP = {"spawn": "spawning", "stop": "stopping"}


@bp.route("servers")
@authenticated
def user_servers(user):
    """Return a JSON of running servers for the user."""
    servers = annotate_servers(get_user_info(user).get("servers", {}))
    return jsonify({"servers": servers})


@bp.route("<namespace>/<project>/<commit_sha>/server_options", methods=["GET"])
@authenticated
def server_options(user, namespace, project, commit_sha):
    """Return a set of configurable server options."""
    server_options_file = os.getenv(
        "NOTEBOOKS_SERVER_OPTIONS_PATH", "/etc/renku-notebooks/server_options.json"
    )
    with open(server_options_file) as f:
        server_options = json.load(f)

    # TODO: append image-specific options to the options json
    return jsonify(server_options)


@bp.route("<namespace>/<project>/<commit_sha>", methods=["GET"])
@bp.route("<namespace>/<project>/<commit_sha>/<path:notebook>", methods=["GET"])
@authenticated
def notebook_status(user, namespace, project, commit_sha, notebook=None):
    """Returns the current status of a user named server or redirect to it if running"""
    name = server_name(namespace, project, commit_sha)

    server = get_user_server(user, namespace, project, commit_sha)
    status = SERVER_STATUS_MAP.get(server.get("pending"), "not found")

    current_app.logger.debug(f"server {name}: {status}")

    return jsonify(server)


@bp.route("<namespace>/<project>/<commit_sha>", methods=["POST"])
@bp.route("<namespace>/<project>/<commit_sha>/<path:notebook>", methods=["POST"])
@authenticated
def launch_notebook(user, namespace, project, commit_sha, notebook=None):
    """Launch user server with a given name."""
    branch = request.args.get("branch", "master")
    # 0. check if server already exists and if so return it
    name = server_name(namespace, project, commit_sha)
    server = get_user_server(user, namespace, project, commit_sha)
    if server:
        return current_app.response_class(
            response=json.dumps(server), status=200, mimetype="application/json"
        )

    # 1. launch using spawner that checks the access
    headers = {auth.auth_header_name: "token {0}".format(auth.api_token)}

    # set the notebook image
    image = get_notebook_image(user, namespace, project, commit_sha)

    # process the server options
    # server options from system configuration
    server_options_file = os.getenv(
        "NOTEBOOKS_SERVER_OPTIONS_PATH", "/etc/renku-notebooks/server_options.json"
    )

    with open(server_options_file) as f:
        server_options_defaults = json.load(f)

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

    # Return 401 if user is not a developer
    if not check_user_has_developer_permission(user, gl_project):
        return current_app.response_class(
            status=401,
            response="Not authorized to use interactive environments for this project.",
        )

    payload = {
        "branch": branch,
        "commit_sha": commit_sha,
        "namespace": namespace,
        "notebook": notebook,
        "project": project,
        "project_id": gl_project.id,
        "image": image,
        "git_clone_image": os.getenv("GIT_CLONE_IMAGE", "renku/git-clone:latest"),
        "server_options": server_options,
    }
    current_app.logger.debug(payload)

    if os.environ.get("GITLAB_REGISTRY_SECRET"):
        payload["image_pull_secrets"] = payload.get("image_pull_secrets", [])
        payload["image_pull_secrets"].append(os.environ["GITLAB_REGISTRY_SECRET"])

    r = requests.request(
        "POST",
        "{prefix}/users/{user[name]}/servers/{server_name}".format(
            prefix=auth.api_url, user=user, server_name=name, image=image
        ),
        json=payload,
        headers=headers,
    )

    # 2. check response, we expect:
    #   - HTTP 201 if the server is already running; in this case redirect to it
    #   - HTTP 202 if the server is spawning
    if r.status_code == 201:
        current_app.logger.debug(
            "server {server_name} already running".format(server_name=name)
        )
    elif r.status_code == 202:
        current_app.logger.debug(
            "spawn initialized for {server_name}".format(server_name=name)
        )
    elif r.status_code == 400:
        current_app.logger.debug("server in pending state")
    else:
        # unexpected status code, abort
        abort(r.status_code)

    # fetch the server from JupyterHub
    server = get_user_server(user, namespace, project, commit_sha)
    return current_app.response_class(
        response=json.dumps(server), status=r.status_code, mimetype="application/json"
    )


@bp.route("<namespace>/<project>/<commit_sha>", methods=["DELETE"])
@authenticated
def stop_notebook(user, namespace, project, commit_sha):
    """Stop user server with name."""
    name = server_name(namespace, project, commit_sha)
    headers = {"Authorization": "token %s" % auth.api_token}

    r = requests.request(
        "DELETE",
        "{prefix}/users/{user[name]}/servers/{server_name}".format(
            prefix=auth.api_url, user=user, server_name=name
        ),
        headers=headers,
    )
    return current_app.response_class(r.content, status=r.status_code)


@bp.route("servers/<server_name>", methods=["DELETE"])
@authenticated
def stop_server(user, server_name):
    """Stop user server with name."""
    headers = {"Authorization": "token %s" % auth.api_token}

    r = requests.request(
        "DELETE",
        "{prefix}/users/{user[name]}/servers/{server_name}".format(
            prefix=auth.api_url, user=user, server_name=server_name
        ),
        headers=headers,
    )
    return current_app.response_class(r.content, status=r.status_code)


@bp.route("<namespace>/<project>/<commit_sha>/logs", methods=["GET"])
@authenticated
def server_logs(user, namespace, project, commit_sha):
    """"Return the logs of the running server."""
    server = get_user_server(user, namespace, project, commit_sha)
    if request.environ["HTTP_ACCEPT"] == "application/json":
        return make_response("Only supporting text/plain.", 406)
    if server:
        pod_name = server.get("state", {}).get("pod_name", "")
        kubernetes_namespace = os.getenv("KUBERNETES_NAMESPACE")
        logs = read_namespaced_pod_log(pod_name, kubernetes_namespace)
        resp = make_response(logs, 200)
    else:
        resp = make_response("", 404)
    resp.mimetype = "text/plain"
    return resp
