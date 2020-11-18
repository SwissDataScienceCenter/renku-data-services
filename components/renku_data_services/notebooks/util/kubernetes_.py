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
"""Kubernetes helper functions."""

import os
import warnings
from datetime import timezone
from pathlib import Path
from urllib.parse import urljoin

import escapism
from flask import current_app
from kubernetes import client
from kubernetes.client.rest import ApiException
from kubernetes.config.config_exception import ConfigException
from kubernetes.config.incluster_config import (
    SERVICE_CERT_FILENAME,
    SERVICE_TOKEN_FILENAME,
    InClusterConfigLoader,
)

from .. import config
from .gitlab_ import _get_oauth_token


# adjust k8s service account paths if running inside telepresence
tele_root = Path(os.getenv("TELEPRESENCE_ROOT", "/"))

token_filename = tele_root / Path(SERVICE_TOKEN_FILENAME).relative_to("/")
cert_filename = tele_root / Path(SERVICE_CERT_FILENAME).relative_to("/")
namespace_path = tele_root / Path(
    "var/run/secrets/kubernetes.io/serviceaccount/namespace"
)

try:
    InClusterConfigLoader(
        token_filename=token_filename, cert_filename=cert_filename
    ).load_and_set()
    v1 = client.CoreV1Api()
except ConfigException:
    v1 = None
    warnings.warn("Unable to configure the kubernetes client.")

try:
    with open(namespace_path, "rt") as f:
        kubernetes_namespace = f.read()
except FileNotFoundError:
    kubernetes_namespace = ""
    warnings.warn(
        "No k8s service account found - not running inside a kubernetes cluster?"
    )


def get_user_servers(user, namespace=None, project=None, branch=None, commit_sha=None):
    """Fetch all the user named servers that matches the provided criteria"""

    def filter_server(server):
        def check_annotation(annotation, value):
            annotation_name = config.RENKU_ANNOTATION_PREFIX + annotation
            if value:
                return server.get("annotations", {}).get(annotation_name, "") == value
            return True

        return (
            check_annotation("namespace", namespace)
            and check_annotation("projectName", project)
            and check_annotation("branch", branch)
            and check_annotation("commit-sha", commit_sha)
        )

    servers = _get_all_user_servers(user)
    filtered_servers = {k: v for k, v in servers.items() if filter_server(v)}
    return filtered_servers


def get_user_server(user, server_name):
    """Fetch the user server with specific name"""
    servers = _get_all_user_servers(user)
    return servers.get(server_name, {})


def delete_user_pod(user, pod_name):
    """Delete user's server with specific name"""
    try:
        v1.delete_namespaced_pod(
            pod_name, kubernetes_namespace, grace_period_seconds=30
        )
        return True
    except ApiException as e:
        msg = f"Cannot delete server: {pod_name} for user: {user}, error: {e}"
        current_app.logger.error(msg)
        return False


def _get_all_user_servers(user):
    def get_user_server_pods(user):
        safe_username = escapism.escape(user["name"], escape_char="-").lower()
        pods = v1.list_namespaced_pod(
            kubernetes_namespace,
            label_selector=f"heritage=jupyterhub,renku.io/username={safe_username}",
        )
        return pods.items

    def isoformat(dt):
        """
        Render a datetime object as an ISO 8601 UTC timestamp.
        Naïve datetime objects are assumed to be UTC
        """
        if dt is None:
            return None
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt.isoformat(timespec="microseconds") + "Z"

    def summarise_pod_conditions(conditions):
        def sort_conditions(conditions):
            CONDITIONS_ORDER = {
                "PodScheduled": 1,
                "Unschedulable": 2,
                "Initialized": 3,
                "ContainersReady": 4,
                "Ready": 5,
            }
            return sorted(conditions, key=lambda c: CONDITIONS_ORDER[c.type])

        if not conditions:
            return {"step": None, "message": None, "reason": None}

        for c in sort_conditions(conditions):
            if (
                (c.type == "Unschedulable" and c.status == "True")
                or (c.status != "True")
                or (c.type == "Ready" and c.status == "True")
            ):
                break
        return {"step": c.type, "message": c.message, "reason": c.reason}

    def get_pod_status(pod):
        try:
            ready = pod.status.container_statuses[0].ready
        except (IndexError, TypeError):
            ready = False

        status = {"phase": pod.status.phase, "ready": ready}
        conditions_summary = summarise_pod_conditions(pod.status.conditions)
        status.update(conditions_summary)
        return status

    def get_pod_resources(pod):
        try:
            resources = pod.spec.containers[0].resources.requests
            # translate the cpu weird numeric string to a normal number
            # ref: https://kubernetes.io/docs/concepts/configuration/
            #   manage-compute-resources-container/#how-pods-with-resource-limits-are-run
            if (
                "cpu" in resources
                and isinstance(resources["cpu"], str)
                and str.endswith(resources["cpu"], "m")
                and resources["cpu"][:-1].isdigit()
            ):
                resources["cpu"] = str(int(resources["cpu"][:-1]) / 1000)
        except (AttributeError, IndexError):
            resources = {}
        return resources

    def get_server_url(pod):
        url = "{jh_path_prefix}/user/{username}/{servername}/".format(
            jh_path_prefix=config.JUPYTERHUB_PATH_PREFIX.rstrip("/"),
            username=pod.metadata.annotations["hub.jupyter.org/username"],
            servername=pod.metadata.annotations["hub.jupyter.org/servername"],
        )
        return urljoin(config.JUPYTERHUB_ORIGIN, url)

    pods = get_user_server_pods(user)

    servers = {
        pod.metadata.annotations["hub.jupyter.org/servername"]: {
            "annotations": pod.metadata.annotations,
            "name": pod.metadata.annotations["hub.jupyter.org/servername"],
            "state": {"pod_name": pod.metadata.name},
            "started": isoformat(pod.status.start_time),
            "status": get_pod_status(pod),
            "url": get_server_url(pod),
            "resources": get_pod_resources(pod),
        }
        for pod in pods
    }
    return servers


def read_namespaced_pod_log(pod_name, max_log_lines=0):
    """
    Read pod's logs.
    """
    if max_log_lines == 0:
        logs = v1.read_namespaced_pod_log(pod_name, kubernetes_namespace)
    else:
        logs = v1.read_namespaced_pod_log(
            pod_name, kubernetes_namespace, tail_lines=max_log_lines
        )
    return logs


def create_registry_secret(user, namespace, secret_name, project, commit_sha, git_host):
    """Create a registry secret for a user."""
    import base64
    import json

    token = _get_oauth_token(user)
    payload = {
        "auths": {
            current_app.config.get("IMAGE_REGISTRY"): {
                "Username": "oauth2",
                "Password": token,
                "Email": user.get("email"),
            }
        }
    }

    data = {
        ".dockerconfigjson": base64.b64encode(json.dumps(payload).encode()).decode()
    }

    safe_username = escapism.escape(user.get("name"), escape_char="-").lower()
    secret = client.V1Secret(
        api_version="v1",
        data=data,
        kind="Secret",
        metadata={
            "name": secret_name,
            "namespace": kubernetes_namespace,
            "labels": {
                "component": "singleuser-server",
                current_app.config.get("RENKU_ANNOTATION_PREFIX")
                + "username": safe_username,
                current_app.config.get("RENKU_ANNOTATION_PREFIX")
                + "commit-sha": commit_sha,
                current_app.config.get("RENKU_ANNOTATION_PREFIX")
                + "projectName": project,
                current_app.config.get("RENKU_ANNOTATION_PREFIX")
                + "git-host": git_host,
                current_app.config.get("RENKU_ANNOTATION_PREFIX")
                + "namespace": namespace,
            },
        },
        type="kubernetes.io/dockerconfigjson",
    )

    if _secret_exists(secret_name, kubernetes_namespace):
        v1.replace_namespaced_secret(secret_name, kubernetes_namespace, secret)
    else:
        v1.create_namespaced_secret(kubernetes_namespace, body=secret)

    return secret


def _secret_exists(name, namespace):
    """Check if the secret exists."""

    try:
        v1.read_namespaced_secret(name, namespace)
        return True
    except client.rest.ApiException:
        pass
    return False
