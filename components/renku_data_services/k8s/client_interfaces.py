"""Required interfaces for k8s clients."""

from typing import Protocol

from kubernetes_asyncio.client import V1DeleteOptions, V1PriorityClass, V1ResourceQuota, V1Secret


class ResourceQuotaClient(Protocol):
    """Methods to manipulate ResourceQuota kubernetes resources."""

    def list_resource_quota(self, namespace: str, label_selector: str) -> list[V1ResourceQuota]:
        """List resource quotas."""
        ...

    def read_resource_quota(self, name: str, namespace: str) -> V1ResourceQuota:
        """Get a resource quota."""
        ...

    def create_resource_quota(self, namespace: str, body: V1ResourceQuota) -> None:
        """Create a resource quota."""
        ...

    def delete_resource_quota(self, name: str, namespace: str) -> None:
        """Delete a resource quota."""
        ...

    def patch_resource_quota(self, name: str, namespace: str, body: V1ResourceQuota) -> None:
        """Update a resource quota."""
        ...


class SecretClient(Protocol):
    """Methods to manipulate Secret kubernetes resources."""

    def create_secret(self, namespace: str, body: V1Secret) -> None:
        """Create a secret."""
        ...

    def patch_secret(self, name: str, namespace: str, body: V1Secret) -> None:
        """Patch an existing secret."""
        ...


class PriorityClassClient(Protocol):
    """Methods to manipulate kubernetes Priority Class resources."""

    def create_priority_class(self, body: V1PriorityClass) -> V1PriorityClass:
        """Create a priority class."""
        ...

    def read_priority_class(self, name: str) -> V1PriorityClass | None:
        """Retrieve a priority class."""
        ...

    def delete_priority_class(self, name: str, body: V1DeleteOptions) -> None:
        """Delete a priority class."""
        ...
