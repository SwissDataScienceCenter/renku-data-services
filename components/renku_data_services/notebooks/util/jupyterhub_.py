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

import json
import os
from hashlib import md5
from urllib.parse import urljoin

import requests
from jupyterhub.services.auth import HubOAuth


auth = HubOAuth(
    api_token=os.environ.get("JUPYTERHUB_API_TOKEN", "token"), cache_max_age=60
)
"""Wrap JupyterHub authentication service API."""
__prefix = auth.api_url
__headers = {auth.auth_header_name: f"token {auth.api_token}"}


def make_server_name(namespace, project, branch, commit_sha):
    """Form a 16-digit hash server ID."""
    server_string = f"{namespace}{project}{branch}{commit_sha}"
    return md5(server_string.encode()).hexdigest()[:16]


def notebook_url(user, server_name, notebook=None):
    """Form the notebook server URL."""
    notebook_url = urljoin(
        os.environ.get("JUPYTERHUB_BASE_URL"),
        "user/{user[name]}/{server_name}/".format(user=user, server_name=server_name),
    )
    if notebook:
        notebook_url += "lab/tree/{notebook}".format(notebook=notebook)
    return notebook_url


def check_user_has_named_server(user, server_name):
    """Check if the named-server exists in user's JupyterHub servers"""
    user_info = get_user_info(user)
    servers = user_info.get("servers")
    return servers is not None and server_name in servers


def get_user_info(user):
    """Return the full user object."""
    response = requests.get(f"{__prefix}/users/{user['name']}", headers=__headers)
    user_info = json.loads(response.text)
    return user_info


def create_named_server(user, server_name, payload):
    """Create a named-server for user"""
    return requests.post(
        f"{__prefix}/users/{user['name']}/servers/{server_name}",
        json=payload,
        headers=__headers,
    )


def delete_named_server(user, server_name):
    """Delete a named-server"""
    return requests.delete(
        f"{__prefix}/users/{user['name']}/servers/{server_name}", headers=__headers
    )
