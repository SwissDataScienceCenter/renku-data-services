import os


GITLAB_URL = os.environ.get('GITLAB_URL', 'https://gitlab.com')
"""The GitLab instance to use."""

IMAGE_REGISTRY = os.environ.get('IMAGE_REGISTRY', '')
"""The default image registry."""

JUPYTERHUB_ANNOTATION_PREFIX = 'hub.jupyter.org'
"""The prefix used for annotations by the KubeSpawner."""

JUPYTERHUB_API_TOKEN = os.environ.get('JUPYTERHUB_API_TOKEN', '')
"""The service api token."""

RENKU_ANNOTATION_PREFIX = 'renku.io/'
"""The prefix used for annotations by Renku."""

SENTRY_DSN = os.environ.get('SENTRY_DSN', '')
"""Sentry client registration."""

SERVICE_PREFIX = os.environ.get('JUPYTERHUB_SERVICE_PREFIX', '/')
"""Service prefix is set by JupyterHub service spawner."""
