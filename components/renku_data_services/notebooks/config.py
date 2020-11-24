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


GITLAB_URL = os.environ.get("GITLAB_URL", "https://gitlab.com")
"""The GitLab instance to use."""

IMAGE_REGISTRY = os.environ.get("IMAGE_REGISTRY", "")
"""The default image registry."""

JUPYTERHUB_ANNOTATION_PREFIX = "hub.jupyter.org"
"""The prefix used for annotations by the KubeSpawner."""

JUPYTERHUB_API_TOKEN = os.environ.get("JUPYTERHUB_API_TOKEN", "")
"""The service api token."""

JUPYTERHUB_ORIGIN = os.environ.get("JUPYTERHUB_ORIGIN", "")
"""Origin property of Jupyterhub, typically https://renkudomain.org"""

RENKU_ANNOTATION_PREFIX = "renku.io/"
"""The prefix used for annotations by Renku."""

SENTRY_DSN = os.environ.get("SENTRY_DSN", "")
"""Sentry client registration."""

SENTRY_ENV = os.environ.get("SENTRY_ENV", "")
"""Sentry client environment."""

SERVICE_PREFIX = os.environ.get("JUPYTERHUB_SERVICE_PREFIX", "/")
"""Service prefix is set by JupyterHub service spawner."""

GITLAB_AUTH = os.environ.get("JUPYTERHUB_AUTHENTICATOR", "gitlab") == "gitlab"
"""Check if we're authenticating with GitLab (and thus have a GitLab oauth token)."""

JUPYTERHUB_PATH_PREFIX = os.environ.get("JUPYTERHUB_BASE_URL", "/jupyterhub")
"""Base path under which Jupyterhub is running."""

DEFAULT_IMAGE = os.environ.get("NOTEBOOKS_DEFAULT_IMAGE", "renku/singleuser:latest")
"""The default image to use for an interactive session if the image tied to the
current commit cannot be found."""
