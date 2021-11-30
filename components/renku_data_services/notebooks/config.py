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
"""Notebooks service configuration."""
import os
from yaml import safe_load

from .util.misc import read_server_options_defaults, read_server_options_ui

GITLAB_URL = os.environ.get("GITLAB_URL", "https://gitlab.com")
"""The GitLab instance to use."""

IMAGE_REGISTRY = os.environ.get("IMAGE_REGISTRY", "")
"""The default image registry."""

JUPYTER_ANNOTATION_PREFIX = "jupyter.org/"
"""The prefix used for annotations by the KubeSpawner."""

RENKU_ANNOTATION_PREFIX = "renku.io/"
"""The prefix used for annotations by Renku."""

SENTRY_DSN = os.environ.get("SENTRY_DSN", "")
"""Sentry client registration."""

SENTRY_ENV = os.environ.get("SENTRY_ENV", "")
"""Sentry client environment."""

SERVICE_PREFIX = os.environ.get("SERVICE_PREFIX", "/notebooks")
"""Service prefix for the notebooks API."""

DEFAULT_IMAGE = os.environ.get("NOTEBOOKS_DEFAULT_IMAGE", "renku/singleuser:latest")
"""The default image to use for an interactive session if the image tied to the
current commit cannot be found."""

GIT_RPC_SERVER_IMAGE = os.environ.get(
    "GIT_RPC_SERVER_IMAGE", "renku/git-sidecar:latest"
)
"""The image used to clone the git repository when a user session is started"""

GIT_HTTPS_PROXY_IMAGE = os.environ.get(
    "GIT_HTTPS_PROXY_IMAGE", "renku/git-https-proxy:latest"
)
"""The HTTPS proxy sidecar container image."""

GIT_CLONE_IMAGE = os.environ.get("GIT_CLONE_IMAGE", "renku/git-clone:latest")
"""The git clone init container image."""

NOTEBOOKS_SESSION_PVS_ENABLED = (
    os.environ.get("NOTEBOOKS_SESSION_PVS_ENABLED", "false") == "true"
)
"""Whether to use persistent volumes for user sessions.
Default is false, in which case ephemeral volumes are used."""

NOTEBOOKS_SESSION_PVS_STORAGE_CLASS = os.environ.get(
    "NOTEBOOKS_SESSION_PVS_STORAGE_CLASS",
)
"""Use a custom storage class for the user session persistent volumes."""

USE_EMPTY_DIR_SIZE_LIMIT = (
    os.environ.get("USE_EMPTY_DIR_SIZE_LIMIT", "false").lower() == "true"
)

OPENAPI_VERSION = "2.0"
API_SPEC_URL = f"{SERVICE_PREFIX}/spec.json"

SERVER_OPTIONS_DEFAULTS = read_server_options_defaults()
SERVER_OPTIONS_UI = read_server_options_ui()

OIDC_CLIENT_ID = os.environ.get("OIDC_CLIENT_ID", "renku")
OIDC_CLIENT_SECRET = os.environ.get("OIDC_CLIENT_SECRET")
OIDC_TOKEN_URL = os.environ.get("OIDC_TOKEN_URL")
OIDC_AUTH_URL = os.environ.get("OIDC_AUTH_URL")
OIDC_ALLOW_UNVERIFIED_EMAIL = os.environ.get("OIDC_ALLOW_UNVERIFIED_EMAIL")

CRD_GROUP = os.environ.get("CRD_GROUP")
CRD_VERSION = os.environ.get("CRD_VERSION")
CRD_PLURAL = os.environ.get("CRD_PLURAL")

SESSION_HOST = os.environ.get("SESSION_HOST")
SESSION_TLS_SECRET = os.environ.get("SESSION_TLS_SECRET")
SESSION_INGRESS_ANNOTATIONS = safe_load(os.environ.get("SESSION_INGRESS_ANNOTATIONS"))

ANONYMOUS_SESSIONS_ENABLED = (
    os.environ.get("ANONYMOUS_SESSIONS_ENABLED", "false").lower() == "true"
)

AMALTHEA_CONTAINER_ORDER_ANONYMOUS_SESSION = [
    "jupyter-server",
]
AMALTHEA_CONTAINER_ORDER_REGISTERED_SESSION = [
    *AMALTHEA_CONTAINER_ORDER_ANONYMOUS_SESSION,
    "oauth2-proxy",
]

IMAGE_DEFAULT_WORKDIR = "/home/jovyan"

CULLING_REGISTERED_IDLE_SESSIONS_THRESHOLD_SECONDS = int(
    os.getenv("CULLING_REGISTERED_IDLE_SESSIONS_THRESHOLD_SECONDS", 86400)
)
CULLING_ANONYMOUS_IDLE_SESSIONS_THRESHOLD_SECONDS = int(
    os.getenv("CULLING_ANONYMOUS_IDLE_SESSIONS_THRESHOLD_SECONDS", 43200)
)

SESSION_NODE_SELECTOR = safe_load(os.environ.get("SESSION_NODE_SELECTOR", "{}"))
SESSION_AFFINITY = safe_load(os.environ.get("SESSION_AFFINITY", "{}"))
SESSION_TOLERATIONS = safe_load(os.environ.get("SESSION_TOLERATIONS", "[]"))
ENFORCE_CPU_LIMITS = os.getenv("ENFORCE_CPU_LIMITS", "off")
