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
"""Functions for interfacing with JupyterHub."""

import os
import string
from functools import partial
from urllib.parse import urljoin

import escapism
from flask import Blueprint, current_app

from .. import config
from ..api.auth import get_user_info

bp = Blueprint("jh_bp", __name__, url_prefix=config.SERVICE_PREFIX)

RENKU_ANNOTATION_PREFIX = config.RENKU_ANNOTATION_PREFIX


def server_name(namespace, project, commit_sha):
    """Form a DNS-safe server name."""
    escape = partial(
        escapism.escape,
        safe=set(string.ascii_lowercase + string.digits),
        escape_char="-",
    )
    return "{namespace}-{project}-{commit_sha}".format(
        namespace=escape(namespace)[:10],
        project=escape(project)[:10],
        commit_sha=commit_sha[:7],
    ).lower()


def notebook_url(user, server_name, notebook=None):
    """Form the notebook server URL."""
    notebook_url = urljoin(
        os.environ.get("JUPYTERHUB_BASE_URL"),
        "user/{user[name]}/{server_name}/".format(user=user, server_name=server_name),
    )
    if notebook:
        notebook_url += "lab/tree/{notebook}".format(notebook=notebook)
    return notebook_url


def get_user_server(user, namespace, project, commit_sha):
    """Fetch the user named server"""
    user_info = get_user_info(user)
    servers = user_info.get("servers", {})
    for server in servers.values():
        annotations = server.get("annotations", {})
        if (
            annotations.get(RENKU_ANNOTATION_PREFIX + "namespace") == namespace
            and annotations.get(RENKU_ANNOTATION_PREFIX + "projectName") == project
            and annotations.get(RENKU_ANNOTATION_PREFIX + "commit-sha") == commit_sha
        ):
            current_app.logger.debug(server)
            return server
    return {}
