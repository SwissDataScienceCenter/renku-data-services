import os
from pathlib import Path

from flask import current_app
from kubernetes import client, config
from kubernetes.config.incluster_config import (
    SERVICE_CERT_FILENAME, SERVICE_TOKEN_FILENAME, InClusterConfigLoader
)

# adjust k8s service account paths if running inside telepresence
token_filename = Path(os.getenv('TELEPRESENCE_ROOT', '/')
                      ) / Path(SERVICE_TOKEN_FILENAME).relative_to('/')
cert_filename = Path(os.getenv('TELEPRESENCE_ROOT', '/')
                     ) / Path(SERVICE_CERT_FILENAME).relative_to('/')
namespace_path = Path(
    os.getenv('TELEPRESENCE_ROOT', '/')
) / Path('var/run/secrets/kubernetes.io/serviceaccount/namespace')

InClusterConfigLoader(
    token_filename=token_filename, cert_filename=cert_filename
).load_and_set()

try:
    with open(namespace_path, 'rt') as f:
        kubernetes_namespace = f.read()
except (config.ConfigException, FileNotFoundError):
    current_app.logger.warning(
        'No k8s service account found - not running inside a kubernetes cluster?'
    )

v1 = client.CoreV1Api()


def _get_pods():
    """Get the running pods."""
    pods = v1.list_namespaced_pod(
        kubernetes_namespace, label_selector='heritage = jupyterhub'
    )
    return pods

def annotate_servers(servers):
    """Get servers with renku annotations."""
    pods = _get_pods().items
    annotations = {pod.metadata.name: pod.metadata.annotations for pod in pods}

    for server_name, properties in servers.items():
        pod_annotations = annotations.get(
            properties.get('state', {}).get('pod_name', {}), {}
        )
        servers[server_name]['annotations'] = {
            key: value
            for (key, value) in pod_annotations.items()
            if key.startswith(current_app.config.get('RENKU_ANNOTATION_PREFIX'))
        }
    return servers
