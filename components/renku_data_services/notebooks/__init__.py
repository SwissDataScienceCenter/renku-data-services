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

from flask import Flask, jsonify
from flask_swagger_ui import get_swaggerui_blueprint
from flask_apispec import FlaskApiSpec
from apispec.ext.marshmallow import MarshmallowPlugin
from apispec import APISpec
import os

from . import config
from .api.notebooks import (
    bp as notebooks_bp,
    user_servers,
    user_server,
    launch_notebook,
    stop_server,
    server_options,
    server_logs,
    autosave_info,
    delete_autosave,
)
from .api.auth import bp as auth_bp, whoami


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

    app.config.from_object(config)

    from .api import blueprints

    for bp in blueprints:
        app.register_blueprint(bp)

    # Return validation errors as JSON
    @app.errorhandler(422)
    def handle_error(err):
        headers = err.data.get("headers", None)
        messages = err.data.get("messages", {"error": "Invalid request."})
        app.logger.warning(
            f"Validation of request parameters failed with the messages: {messages}"
        )
        if headers:
            return jsonify({"messages": messages}), err.code, headers
        else:
            return jsonify({"messages": messages}), err.code

    app.logger.debug(app.config)

    if "SENTRY_DSN" in app.config:
        import sentry_sdk
        from sentry_sdk.integrations.flask import FlaskIntegration

        sentry_sdk.init(
            dsn=app.config.get("SENTRY_DSN"),
            environment=app.config.get("SENTRY_ENV"),
            integrations=[FlaskIntegration()],
        )
    return app


def register_swagger(app):
    apispec = APISpec(
        title="Renku Notebooks API",
        openapi_version=config.OPENAPI_VERSION,
        version="v1",
        plugins=[MarshmallowPlugin()],
        produces=["text/plain"],
        security=[{"token": []}],
    )
    security_scheme = {
        "type": "apiKey",
        "in": "header",
        "name": "Authorization",
        "description": "Use the jupyterhub API token here. Include the word 'token', "
        "a single space and the actual token as the value in the form."
        "The token can be acquired by visiting "
        f"{config.JUPYTERHUB_ORIGIN}/{config.JUPYTERHUB_PATH_PREFIX}/hub/token.",
    }
    apispec.components.security_scheme("token", security_scheme)
    app.config.update(
        {"APISPEC_SPEC": apispec, "APISPEC_SWAGGER_URL": config.API_SPEC_URL}
    )
    swaggerui_blueprint = get_swaggerui_blueprint(
        config.SWAGGER_URL, config.API_SPEC_URL, config={"app_name": "Renku Notebooks"}
    )
    app.register_blueprint(swaggerui_blueprint, url_prefix=config.SWAGGER_URL)
    docs = FlaskApiSpec(app, document_options=False)
    docs.register(user_servers, blueprint=notebooks_bp.name)
    docs.register(user_server, blueprint=notebooks_bp.name)
    docs.register(launch_notebook, blueprint=notebooks_bp.name)
    docs.register(stop_server, blueprint=notebooks_bp.name)
    docs.register(server_options, blueprint=notebooks_bp.name)
    docs.register(server_logs, blueprint=notebooks_bp.name)
    docs.register(autosave_info, blueprint=notebooks_bp.name)
    docs.register(delete_autosave, blueprint=notebooks_bp.name)
    docs.register(whoami, blueprint=auth_bp.name)
    return app
