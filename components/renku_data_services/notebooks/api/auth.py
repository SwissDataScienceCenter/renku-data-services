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

from flask import Blueprint, current_app, jsonify, request

from .. import config
from .classes.user import AnonymousUser, RegisteredUser

bp = Blueprint("auth_bp", __name__, url_prefix=config.SERVICE_PREFIX)


def authenticated(f):
    """Decorator for checking authentication status of the user given the headers."""

    @wraps(f)
    def decorated(*args, **kwargs):
        current_app.logger.debug(f"Getting headers, {list(request.headers.keys())}")
        user = RegisteredUser(request.headers)
        if current_app.config["ANONYMOUS_SESSIONS_ENABLED"] and not user.authenticated:
            user = AnonymousUser(request.headers)
        if user.authenticated:
            # the user is logged in
            return f(user, *args, **kwargs)
        else:
            # the user is not logged in
            response = jsonify(
                {
                    "messages": {
                        "error": "The required authentication headers "
                        f"{RegisteredUser.auth_headers} are missing. "
                        "If anonymous user sessions are supported then the header "
                        f"{AnonymousUser.auth_header} can also be used."
                    }
                }
            )
            response.status_code = 401
            return response

    return decorated
