"""Different implementations of k8s clients."""
from copy import deepcopy
from multiprocessing import Lock
from typing import Any, Dict
from uuid import uuid4

from kubernetes import client, config
from kubernetes.config.config_exception import ConfigException
from kubernetes.config.incluster_config import SERVICE_CERT_FILENAME, SERVICE_TOKEN_FILENAME, InClusterConfigLoader

from k8s.client_interfaces import K8sCoreClientInterface, K8sSchedudlingClientInterface


class K8sCoreClient(K8sCoreClientInterface):  # pragma:nocover
    """Real k8s core API client that exposes the required functions."""

    def __init__(self):
        try:
            InClusterConfigLoader(
                token_filename=SERVICE_TOKEN_FILENAME,
                cert_filename=SERVICE_CERT_FILENAME,
            ).load_and_set()
        except ConfigException:
            config.load_config()
        self.client = client.CoreV1Api()

    def read_namespaced_resource_quota(self, name: Any, namespace: Any, **kwargs: Any) -> Any:
        """Get a resource quota."""
        return self.client.read_namespaced_resource_quota(name, namespace, **kwargs)

    def list_namespaced_resource_quota(self, namespace: Any, **kwargs: Any) -> Any:
        """List resource quotas."""
        return self.client.list_namespaced_resource_quota(namespace, **kwargs)

    def create_namespaced_resource_quota(self, namespace: Any, body: Any, **kwargs: Any) -> Any:
        """Create a resource quota."""
        return self.client.create_namespaced_resource_quota(namespace, body, **kwargs)

    def delete_namespaced_resource_quota(self, name: Any, namespace: Any, **kwargs: Any) -> Any:
        """Delete a resource quota."""
        return self.client.delete_namespaced_resource_quota(name, namespace, **kwargs)

    def patch_namespaced_resource_quota(self, name: Any, namespace: Any, body: Any, **kwargs: Any) -> Any:
        """Update a resource quota."""
        return self.client.patch_namespaced_resource_quota(name, namespace, body, **kwargs)


class K8sSchedulingClient(K8sSchedudlingClientInterface):  # pragma:nocover
    """Real k8s scheduling API client that exposes the required functions."""

    def __init__(self):
        try:
            InClusterConfigLoader(
                token_filename=SERVICE_TOKEN_FILENAME,
                cert_filename=SERVICE_CERT_FILENAME,
            ).load_and_set()
        except ConfigException:
            config.load_config()
        self.client = client.SchedulingV1Api()

    def create_priority_class(self, body: Any, **kwargs: Any) -> Any:
        """Create a priority class."""
        return self.client.create_priority_class(body, **kwargs)

    def delete_priority_class(self, name: Any, **kwargs: Any) -> Any:
        """Delete a priority class."""
        return self.client.delete_priority_class(name, **kwargs)


class DummyCoreClient(K8sCoreClientInterface):
    """Dummy k8s core API client that does not require a k8s cluster.

    Not suitable for production - to be used only for testing and development.
    """

    def __init__(self, quotas: Dict[str, client.V1ResourceQuota]):
        self.quotas = quotas
        self._lock = Lock()

    def read_namespaced_resource_quota(self, name: Any, namespace: Any, **kwargs: Any) -> Any:
        """Get a resource quota."""
        with self._lock:
            quota = self.quotas.get(name)
            if quota is None:
                raise client.ApiException(status=404)
            return quota

    def list_namespaced_resource_quota(self, namespace: Any, **kwargs: Any) -> Any:
        """List resource quotas."""
        with self._lock:
            return client.V1ResourceQuotaList(items=list(self.quotas.values()))

    def create_namespaced_resource_quota(self, namespace: Any, body: Any, **kwargs: Any) -> Any:
        """Create a resource quota."""
        with self._lock:
            if isinstance(body.metadata, dict):
                body.metadata = client.V1ObjectMeta(**body.metadata)
            body.metadata.uid = uuid4()
            body.api_version = "v1"
            body.kind = "ResourceQuota"
            self.quotas[body.metadata.name] = body
            return body

    def delete_namespaced_resource_quota(self, name: Any, namespace: Any, **kwargs: Any) -> Any:
        """Delete a resource quota."""
        with self._lock:
            removed_quota = self.quotas.pop(name, None)
            if removed_quota is None:
                raise client.ApiException(status=404)
            return removed_quota

    def patch_namespaced_resource_quota(self, name: Any, namespace: Any, body: Any, **kwargs: Any) -> Any:
        """Update a resource quota."""
        with self._lock:
            old_quota = self.quotas.get(name)
            if old_quota is None:
                raise client.ApiException(status=404)
            new_quota = deepcopy(old_quota)
            if isinstance(body, client.V1ResourceQuota):
                new_quota.spec = body.spec
            if isinstance(body, dict):
                new_quota.spec = client.V1ResourceQuota(**body).spec
            self.quotas[name] = new_quota
            return new_quota


class DummySchedulingClient(K8sSchedudlingClientInterface):
    """Dummy k8s scheduling API client that does not require a k8s cluster.

    Not suitable for production - to be used only for testing and development.
    """

    def __init__(self, pcs: Dict[str, client.V1PriorityClass]):
        self.pcs = pcs
        self._lock = Lock()

    def create_priority_class(self, body: Any, **kwargs: Any) -> Any:
        """Create a priority class."""
        with self._lock:
            if isinstance(body.metadata, dict):
                body.metadata = client.V1ObjectMeta(**body.metadata)
            body.metadata.uid = uuid4()
            body.api_version = "v1"
            body.kind = "PriorityClass"
            self.pcs[body.metadata.name] = body
            return body

    def delete_priority_class(self, name: Any, **kwargs: Any) -> Any:
        """Delete a priority class."""
        with self._lock:
            removed_pc = self.pcs.pop(name, None)
            if removed_pc is None:
                raise client.ApiException(status=404)
            return removed_pc
