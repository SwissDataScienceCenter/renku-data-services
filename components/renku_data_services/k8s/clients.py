"""Different implementations of k8s clients."""

import multiprocessing.synchronize
from copy import deepcopy
from multiprocessing import Lock
from multiprocessing.synchronize import Lock as LockType
from typing import Any
from uuid import uuid4

from kubernetes import client
from kubernetes.config import new_client_from_config, ConfigException

from renku_data_services.k8s.client_interfaces import K8sCoreClientInterface, K8sSchedudlingClientInterface


class K8sCoreClient(K8sCoreClientInterface):  # pragma:nocover
    """Real k8s core API client that exposes the required functions."""

    def __init__(self, config_file: str | None = None) -> None:
        try:
            api = new_client_from_config(config_file=config_file)
        except ConfigException:
            api = None

        self.client = client.CoreV1Api(api_client=api)

    def read_namespaced_resource_quota(self, name: str, namespace: str, **kwargs: dict) -> Any:
        """Get a resource quota."""
        return self.client.read_namespaced_resource_quota(name, namespace, **kwargs)

    def list_namespaced_resource_quota(self, namespace: str, **kwargs: dict) -> Any:
        """List resource quotas."""
        return self.client.list_namespaced_resource_quota(namespace, **kwargs)

    def create_namespaced_resource_quota(self, namespace: str, body: dict, **kwargs: dict) -> Any:
        """Create a resource quota."""
        return self.client.create_namespaced_resource_quota(namespace, body, **kwargs)

    def delete_namespaced_resource_quota(self, name: str, namespace: str, **kwargs: dict) -> Any:
        """Delete a resource quota."""
        return self.client.delete_namespaced_resource_quota(name, namespace, **kwargs)

    def patch_namespaced_resource_quota(self, name: str, namespace: str, body: dict, **kwargs: dict) -> Any:
        """Update a resource quota."""
        return self.client.patch_namespaced_resource_quota(name, namespace, body, **kwargs)

    def delete_namespaced_secret(self, name: str, namespace: str, **kwargs: dict) -> Any:
        """Delete a secret."""
        return self.client.delete_namespaced_secret(name, namespace, **kwargs)

    def create_namespaced_secret(self, namespace: str, body: dict, **kwargs: dict) -> Any:
        """Create a secret."""
        return self.client.create_namespaced_secret(namespace, body, **kwargs)

    def patch_namespaced_secret(self, name: str, namespace: str, body: dict, **kwargs: dict) -> Any:
        """Patch a secret."""
        return self.client.patch_namespaced_secret(name, namespace, body, **kwargs)


class K8sSchedulingClient(K8sSchedudlingClientInterface):  # pragma:nocover
    """Real k8s scheduling API client that exposes the required functions."""

    def __init__(self, config_file: str | None = None) -> None:
        try:
            api = new_client_from_config(config_file=config_file)
        except ConfigException:
            api = None

        self.client = client.SchedulingV1Api(api_client=api)

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

    def __init__(self, quotas: dict[str, client.V1ResourceQuota], secrets: dict[str, client.V1Secret]) -> None:
        self.quotas = quotas
        self.secrets = secrets
        self.__lock: LockType | None = None

    @property
    def _lock(self) -> multiprocessing.synchronize.Lock:
        # NOTE: If this is a regular attribute and initialized when the class in initialized
        # then Sanic fails to start properly because it clashes with the multiprocessing Lock
        # used here. This way Sanic starts without a problem because the Lock is initialized
        # after Sanic has started.
        if not self.__lock:
            self.__lock = Lock()
        return self.__lock

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

    def create_namespaced_secret(self, namespace: Any, body: Any, **kwargs: Any) -> Any:
        """Create a secret."""
        with self._lock:
            if isinstance(body.metadata, dict):
                body.metadata = client.V1ObjectMeta(**body.metadata)
            body.metadata.uid = uuid4()
            body.api_version = "v1"
            body.kind = "Secret"
            self.secrets[body.metadata.name] = body
            return body

    def patch_namespaced_secret(self, name: Any, namespace: Any, body: Any, **kwargs: Any) -> Any:
        """Patch a secret."""
        # NOTE: This is only needed if the create_namespaced_secret can raise a conflict 409 status code
        # error when it tries to create a secret that already exists. But the dummy client never raises
        # this so we don't need to implement it (for now).
        raise NotImplementedError()

    def delete_namespaced_secret(self, name: Any, namespace: Any, **kwargs: Any) -> Any:
        """Delete a secret."""
        with self._lock:
            removed_secret = self.secrets.pop(name, None)
            if removed_secret is None:
                raise client.ApiException(status=404)
            return removed_secret


class DummySchedulingClient(K8sSchedudlingClientInterface):
    """Dummy k8s scheduling API client that does not require a k8s cluster.

    Not suitable for production - to be used only for testing and development.
    """

    def __init__(self, pcs: dict[str, client.V1PriorityClass]) -> None:
        self.pcs = pcs
        self.__lock: LockType | None = None

    @property
    def _lock(self) -> multiprocessing.synchronize.Lock:
        # NOTE: If this is a regular attribute and initialized when the class in initialized
        # then Sanic fails to start properly because it clashes with the multiprocessing Lock
        # used here. This way Sanic starts without a problem because the Lock is initialized
        # after Sanic has started.
        if not self.__lock:
            self.__lock = Lock()
        return self.__lock

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
