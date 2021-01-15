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
"""Authentication functions for the notebooks service."""

from functools import wraps
from flask import (
    Blueprint,
    current_app,
    jsonify,
    request,
    make_response,
    redirect,
    abort,
)
from flask_apispec import doc

from .. import config
from .decorators import validate_response_with
from .schemas import User
from ..util.kubernetes_ import get_user_servers
from ..util.jupyterhub_ import auth, get_user_info


bp = Blueprint("auth_bp", __name__, url_prefix=config.SERVICE_PREFIX)


def authenticated(f):
    """Decorator for authenticating with the Hub"""

    @wraps(f)
    def decorated(*args, **kwargs):
        token = (
            request.cookies.get(auth.cookie_name)
            or request.headers.get("Authorization", "")[len("token") :].strip()
        )
        if token:
            user = auth.user_for_token(token)
        else:
            user = None
        if user:
            return f(user, *args, **kwargs)
        else:
            # if the request is not coming from a browser, return 401
            if request.environ.get("HTTP_ACCEPT", "") == "application/json":
                current_app.logger.info(
                    "Unauthorized non-browser request - returning 401."
                )
                response = jsonify(
                    {"messages": {"error": "An authorization token is required."}}
                )
                response.status_code = 401
                return response

            # redirect to login url on failed auth
            state = auth.generate_state(next_url=request.url)
            current_app.logger.debug(
                "Auth flow, redirecting to {} with next url {}".format(
                    auth.login_url, request.url
                )
            )
            response = make_response(
                redirect(auth.login_url + "&state=%s" % state, code=302)
            )
            response.set_cookie(auth.state_cookie_name, state)
            return response

    return decorated


@bp.route("oauth_callback")
def oauth_callback():
    """Set a token in the cookie."""
    code = request.args.get("code", None)
    if code is None:
        abort(403)

    # validate state field
    arg_state = request.args.get("state", None)
    cookie_state = request.cookies.get(auth.state_cookie_name)
    if arg_state is None or arg_state != cookie_state:
        # state doesn't match
        abort(403)

    token = auth.token_for_code(code)
    next_url = auth.get_next_url(cookie_state) or current_app.config.get(
        "SERVICE_PREFIX"
    )
    response = make_response(redirect(next_url, code=302))
    response.set_cookie(auth.cookie_name, token)
    return response


@bp.route("user")
@validate_response_with(
    {
        200: {
            "schema": User(),
            "description": "Information about the authenticated user.",
        }
    }
)
@doc(tags=["user"], summary="Information about the authenticated user.")
@authenticated
def whoami(user):
    """Return information about the authenticated user."""
    user_info = get_user_info(user)
    if user_info == {} or user_info is None:
        return make_response(
            jsonify({"message": {"info": "No information on the authenticated user"}}),
            404,
        )
    user_info["servers"] = get_user_servers(user)
    return make_response(jsonify(user_info), 200)


@bp.route("login-tmp")
@authenticated
def redirect_to_ui(user):
    """Return information about the authenticated user."""
    return make_response(redirect(request.args["redirect_url"], code=302))
