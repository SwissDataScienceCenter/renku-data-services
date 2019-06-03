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
from pathlib import Path

from flask import current_app
from kubernetes import client, config
from kubernetes.config.config_exception import ConfigException
from kubernetes.config.incluster_config import (
    SERVICE_CERT_FILENAME,
    SERVICE_TOKEN_FILENAME,
    InClusterConfigLoader,
)

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
except (config.ConfigException, FileNotFoundError):
    kubernetes_namespace = ""
    warnings.warn(
        "No k8s service account found - not running inside a kubernetes cluster?"
    )


def _get_pods():
    """Get the running pods."""
    pods = v1.list_namespaced_pod(
        kubernetes_namespace, label_selector="heritage = jupyterhub"
    )
    return pods


def annotate_servers(servers):
    """Get servers with renku annotations."""
    pods = _get_pods().items
    annotations = {pod.metadata.name: pod.metadata.annotations for pod in pods}

    for server_name, properties in servers.items():
        pod_annotations = annotations.get(
            properties.get("state", {}).get("pod_name", ""), {}
        )
        servers[server_name]["annotations"] = {
            key: value
            for (key, value) in pod_annotations.items()
            if key.startswith(current_app.config.get("RENKU_ANNOTATION_PREFIX"))
        }
    return servers


def read_namespaced_pod_log(pod_name, kubernetes_namespace):
    return v1.read_namespaced_pod_log(pod_name, kubernetes_namespace)
