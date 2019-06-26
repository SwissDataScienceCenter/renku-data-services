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

import escapism
from flask import current_app
from kubernetes import client
from kubernetes.config.config_exception import ConfigException
from kubernetes.config.incluster_config import (
    SERVICE_CERT_FILENAME,
    SERVICE_TOKEN_FILENAME,
    InClusterConfigLoader,
)
from pathlib import Path
from urllib.parse import urljoin

from .. import config


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


def get_user_server(user, namespace, project, commit_sha):
    """Fetch the user named server"""
    RENKU_ANNOTATION_PREFIX = config.RENKU_ANNOTATION_PREFIX
    servers = get_user_servers(user)
    for server in servers.values():
        annotations = server["annotations"]
        if (
            annotations.get(RENKU_ANNOTATION_PREFIX + "namespace") == namespace
            and annotations.get(RENKU_ANNOTATION_PREFIX + "projectName") == project
            and annotations.get(RENKU_ANNOTATION_PREFIX + "commit-sha") == commit_sha
        ):
            current_app.logger.debug(server)
            return server
    return {}


def get_user_servers(user):
    """Return all notebook servers for the user"""

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

    def get_server_url(pod):
        url = "/jupyterhub/user/{username}/{servername}/".format(
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
        }
        for pod in pods
    }
    return servers


def _get_pods():
    """Get the running pods."""
    pods = v1.list_namespaced_pod(
        kubernetes_namespace, label_selector="heritage = jupyterhub"
    )
    return pods


def read_namespaced_pod_log(pod_name, kubernetes_namespace):
    return v1.read_namespaced_pod_log(pod_name, kubernetes_namespace)
