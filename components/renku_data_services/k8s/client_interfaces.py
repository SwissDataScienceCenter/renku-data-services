"""Required interfaces for k8s clients."""

from __future__ import annotations

from collections.abc import AsyncIterable, AsyncIterator
from typing import Any, Protocol, overload

from kubernetes.client import V1PriorityClass, V1ResourceQuota

from renku_data_services.k8s.constants import ClusterId
from renku_data_services.k8s.models import (
    ClusterScopedK8sObject,
    DeletePropagationPolicy,
    K8sObject,
    K8sObjectFilter,
    K8sObjectMeta,
    K8sSecret,
)


class ResourceQuotaClient(Protocol):
    """Methods to manipulate ResourceQuota kubernetes resources."""

    def list_resource_quota(
        self, namespace: str, label_selector: dict[str, str], cluster_id: ClusterId
    ) -> AsyncIterable[V1ResourceQuota]:
        """List resource quotas."""
        ...

    async def read_resource_quota(self, name: str, namespace: str, cluster_id: ClusterId) -> V1ResourceQuota:
        """Get a resource quota."""
        ...

    async def create_resource_quota(
        self, namespace: str, body: V1ResourceQuota, cluster_id: ClusterId
    ) -> V1ResourceQuota:
        """Create a resource quota."""
        ...

    async def delete_resource_quota(self, name: str, namespace: str, cluster_id: ClusterId) -> None:
        """Delete a resource quota."""
        ...

    async def patch_resource_quota(
        self, name: str, namespace: str, body: V1ResourceQuota, cluster_id: ClusterId
    ) -> V1ResourceQuota:
        """Update a resource quota."""
        ...


class SecretClient(Protocol):
    """Methods to manipulate Secret kubernetes resources."""

    async def create_secret(self, secret: K8sSecret) -> K8sSecret:
        """Create a secret."""
        ...

    async def patch_secret(self, secret: K8sObjectMeta, patch: dict[str, Any] | list[dict[str, Any]]) -> K8sSecret:
        """Patch an existing secret."""
        ...

    async def delete_secret(self, secret: K8sObjectMeta) -> None:
        """Delete a secret."""
        ...


class PriorityClassClient(Protocol):
    """Methods to manipulate kubernetes Priority Class resources."""

    async def create_priority_class(self, body: V1PriorityClass, cluster_id: ClusterId) -> V1PriorityClass:
        """Create a priority class."""
        ...

    async def read_priority_class(self, name: str, cluster_id: ClusterId) -> V1PriorityClass | None:
        """Retrieve a priority class."""
        ...

    async def delete_priority_class(
        self,
        name: str,
        cluster_id: ClusterId,
        propagation_policy: DeletePropagationPolicy = DeletePropagationPolicy.foreground,
    ) -> None:
        """Delete a priority class."""
        ...


class K8sClient(Protocol):
    """Methods to manipulate resources on a Kubernetes cluster."""

    @overload
    async def create(self, obj: K8sObject, refresh: bool) -> K8sObject: ...
    @overload
    async def create(self, obj: ClusterScopedK8sObject, refresh: bool) -> ClusterScopedK8sObject: ...
    async def create(
        self, obj: K8sObject | ClusterScopedK8sObject, refresh: bool
    ) -> K8sObject | ClusterScopedK8sObject:
        """Create the k8s object."""
        ...

    async def patch(self, meta: K8sObjectMeta, patch: dict[str, Any] | list[dict[str, Any]]) -> K8sObject:
        """Patch a k8s object.

        If the patch is a list we assume that we have a rfc6902 json patch like
        `[{ "op": "add", "path": "/a/b/c", "value": [ "foo", "bar" ] }]`.
        If the patch is a dictionary then it is considered to be a rfc7386 json merge patch.
        """
        ...

    async def delete(
        self, meta: K8sObjectMeta, propagation_policy: DeletePropagationPolicy = DeletePropagationPolicy.foreground
    ) -> None:
        """Delete a k8s object."""
        ...

    async def get(self, meta: K8sObjectMeta) -> K8sObject | None:
        """Get a specific k8s object, None is returned if the object does not exist."""
        ...

    def list(self, _filter: K8sObjectFilter) -> AsyncIterable[K8sObject]:
        """List all k8s objects."""
        ...

    async def logs(self, meta: K8sObjectMeta, max_log_lines: int | None = None) -> dict[str, AsyncIterator[str]]:
        """Get the logs of a specific pod, keyed by container names."""
