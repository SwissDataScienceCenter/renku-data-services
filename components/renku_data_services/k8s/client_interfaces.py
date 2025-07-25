"""Required interfaces for k8s clients."""

from typing import Any, Protocol


class ResourceQuotaClient(Protocol):
    """Methods to manipulate ResourceQuota kubernetes resources."""

    def list_namespaced_resource_quota(self, namespace: Any, **kwargs: Any) -> Any:
        """List resource quotas."""
        ...

    def read_namespaced_resource_quota(self, name: Any, namespace: Any, **kwargs: Any) -> Any:
        """Get a resource quota."""
        ...

    def create_namespaced_resource_quota(self, namespace: Any, body: Any, **kwargs: Any) -> Any:
        """Create a resource quota."""
        ...

    def delete_namespaced_resource_quota(self, name: Any, namespace: Any, **kwargs: Any) -> Any:
        """Delete a resource quota."""
        ...

    def patch_namespaced_resource_quota(self, name: Any, namespace: Any, body: Any, **kwargs: Any) -> Any:
        """Update a resource quota."""
        ...


class SecretClient(Protocol):
    """Methods to manipulate Secret kubernetes resources."""

    def delete_namespaced_secret(self, name: Any, namespace: Any, **kwargs: Any) -> Any:
        """Delete a secret."""
        ...

    def create_namespaced_secret(self, namespace: Any, body: Any, **kwargs: Any) -> Any:
        """Create a secret."""
        ...

    def patch_namespaced_secret(self, name: Any, namespace: Any, body: Any, **kwargs: Any) -> Any:
        """Patch an existing secret."""
        ...


class PriorityClassClient(Protocol):
    """Methods to manipulate Priority Class kubernetes resources."""

    def create_priority_class(self, body: Any, **kwargs: Any) -> Any:
        """Create a priority class."""
        ...

    def delete_priority_class(self, name: Any, **kwargs: Any) -> Any:
        """Delete a priority class."""
        ...

    def get_priority_class(self, name: Any, **kwargs: Any) -> Any:
        """Retrieve a priority class."""
        ...
