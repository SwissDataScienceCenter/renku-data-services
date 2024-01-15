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
"""Notebooks service flask app."""

import os

from apispec import APISpec
from apispec.ext.marshmallow import MarshmallowPlugin
from apispec_webframeworks.flask import FlaskPlugin
from flask import Blueprint, Flask, jsonify

from .api.notebooks import (
    check_docker_image,
    launch_notebook,
    patch_server,
    server_logs,
    server_options,
    stop_server,
    user_server,
    user_servers,
)
from .api.schemas.config_server_options import ServerOptionsEndpointResponse
from .api.schemas.errors import ErrorResponse
from .api.schemas.logs import ServerLogs
from .api.schemas.servers_get import NotebookResponse, ServersGetRequest, ServersGetResponse
from .api.schemas.servers_patch import PatchServerRequest
from .api.schemas.servers_post import LaunchNotebookRequest
from .api.schemas.version import VersionResponse
from .config import config as config
from .errors.utils import handle_exception


# From: http://flask.pocoo.org/snippets/35/
class _ReverseProxied(object):
    """Wrap the application in this middleware and configure the
    front-end server to add these headers, to let you quietly bind
    this to a URL other than / and to an HTTP scheme that is
    different than what is used locally.

    :param app: the WSGI application
    """

    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        script_name = environ.get("HTTP_X_SCRIPT_NAME", "")
        if script_name:
            environ["SCRIPT_NAME"] = script_name
            path_info = environ["PATH_INFO"]
            if path_info.startswith(script_name):
                environ["PATH_INFO"] = path_info[len(script_name) :]

        scheme = environ.get("HTTP_X_SCHEME", "")
        if scheme:
            environ["wsgi.url_scheme"] = scheme
        return self.app(environ, start_response)


def create_app():
    """Bootstrap the flask app."""

    # Wait for the VS Code debugger to attach if requested
    VSCODE_DEBUG = os.environ.get("VSCODE_DEBUG") == "1"
    if VSCODE_DEBUG:
        import ptvsd

        print("Waiting for debugger attach")
        ptvsd.enable_attach(address=("localhost", 5678), redirect_output=True)
        ptvsd.wait_for_attach()

    app = Flask(__name__)
    app.wsgi_app = _ReverseProxied(app.wsgi_app)

    from .api.auth import bp as auth_bp
    from .api.health import bp as health_bp
    from .api.notebooks import bp as notebooks_bp

    for bp in [auth_bp, health_bp, notebooks_bp]:
        app.register_blueprint(bp)

    # Return errors as JSON
    app.errorhandler(Exception)(handle_exception)

    app.logger.debug(config)

    if config.sentry.enabled:
        import sentry_sdk
        from sentry_sdk.integrations.flask import FlaskIntegration

        sentry_sdk.init(
            dsn=config.sentry.dsn,
            environment=config.sentry.env,
            integrations=[FlaskIntegration()],
            traces_sample_rate=config.sentry.sample_rate,
        )
    return app


def register_swagger(app):
    spec = APISpec(
        title="Renku Notebooks API",
        openapi_version="3.0.2",
        version="v1",
        plugins=[FlaskPlugin(), MarshmallowPlugin()],
        info={
            "description": "An API to launch and manage Jupyter servers for Renku. "
            "To get authorized select the `OAuth2, authorizationCode` flow and the "
            "`openid` scope. Scroll up to find the proper flow in the list. "
            "If the deployment supports anonymous sessions you can also use the API "
            "without getting authorized at all."
        },
        security=[{"oauth2-swagger": ["openid"]}],
        servers=[{"url": "/api"}, {"url": "/ui-server/api"}],
    )
    # Register schemas
    spec.components.schema("LaunchNotebookRequest", schema=LaunchNotebookRequest)
    spec.components.schema("NotebookResponse", schema=NotebookResponse)
    spec.components.schema("PatchServerRequest", schema=PatchServerRequest)
    spec.components.schema("ServersGetRequest", schema=ServersGetRequest)
    spec.components.schema("ServersGetResponse", schema=ServersGetResponse)
    spec.components.schema("ServerLogs", schema=ServerLogs)
    spec.components.schema("ServerOptionsEndpointResponse", schema=ServerOptionsEndpointResponse)
    spec.components.schema("VersionResponse", schema=VersionResponse)
    spec.components.schema("ErrorResponse", schema=ErrorResponse)
    # Register endpoints
    with app.test_request_context():
        spec.path(view=user_server)
        spec.path(view=user_servers)
        spec.path(view=launch_notebook)
        spec.path(view=patch_server)
        spec.path(view=stop_server)
        spec.path(view=server_options)
        spec.path(view=server_logs)
        spec.path(view=check_docker_image)
    # Register security scheme
    security_scheme = {
        "type": "openIdConnect",
        "description": "PKCE flow for swagger.",
        "openIdConnectUrl": config.sessions.oidc.config_url,
    }
    spec.components.security_scheme("oauth2-swagger", security_scheme)

    bp = Blueprint("swagger_blueprint", __name__, url_prefix=config.service_prefix)

    @bp.route("spec.json")
    def render_openapi_spec():
        return jsonify(spec.to_dict())

    app.register_blueprint(bp)
    return app
