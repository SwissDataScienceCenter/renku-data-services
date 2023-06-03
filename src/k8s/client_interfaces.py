"""Required interfaces for k8s clients."""
from abc import ABC, abstractmethod
from typing import Any


class K8sCoreClientInterface(ABC):
    """Defines what functionality is required for the core k8s client."""

    @abstractmethod
    def read_namespaced_resource_quota(self, name: Any, namespace: Any, **kwargs: Any) -> Any:
        """Get a resource quota."""
        ...

    @abstractmethod
    def list_namespaced_resource_quota(self, namespace: Any, **kwargs: Any) -> Any:
        """List resource quotas."""
        ...

    @abstractmethod
    def create_namespaced_resource_quota(self, body: Any, namespace: Any, **kwargs: Any) -> Any:
        """Create a resource quota."""
        ...

    @abstractmethod
    def delete_namespaced_resource_quota(self, name: Any, namespace: Any, **kwargs: Any) -> Any:
        """Delete a resource quota."""
        ...

    @abstractmethod
    def patch_namespaced_resource_quota(self, name: Any, namespace: Any, body: Any, **kwargs: Any) -> Any:
        """Update a resource quota."""
        ...


class K8sSchedudlingClientInterface(ABC):
    """Defines what functionality is required for the scheduling k8s client."""

    @abstractmethod
    def create_priority_class(self, body: Any, **kwargs: Any) -> Any:
        """Create a priority class."""
        ...

    @abstractmethod
    def delete_priority_class(self, name: Any, **kwargs: Any) -> Any:
        """Delete a priority class."""
        ...
