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
"""Integrating interactive environments with GitLab."""
import gitlab
from flask import current_app

from .. import config


def get_renku_project(user, namespace_project):
    """Retrieve the GitLab project."""
    gl = gitlab.Gitlab(
        config.GITLAB_URL, api_version=4, oauth_token=_get_oauth_token(user)
    )
    try:
        return gl.projects.get("{0}".format(namespace_project))
    except Exception as e:
        current_app.logger.error(
            f"Cannot get project: {namespace_project} for user: {user}, error: {e}"
        )


def _get_oauth_token(user):
    """Retrieve the user's GitLab token from the oauth metadata."""
    from ..api.auth import get_user_info

    if not config.GITLAB_AUTH:
        return None

    auth_state = get_user_info(user).get("auth_state", None)
    return None if not auth_state else auth_state.get("access_token")


def check_user_has_developer_permission(user, gl_project):
    return _get_project_permissions(user, gl_project) >= gitlab.DEVELOPER_ACCESS


def _get_project_permissions(user, gl_project):
    """Return the user's access level for the given project."""
    permissions = gl_project.attributes["permissions"]
    access_level = max(
        [x[1].get("access_level", 0) for x in permissions.items() if x[1]]
    )
    current_app.logger.debug(
        "access level for user {username} in {project} = {access_level}".format(
            username=user.get("name"),
            project=gl_project.path_with_namespace,
            access_level=access_level,
        )
    )
    return access_level
