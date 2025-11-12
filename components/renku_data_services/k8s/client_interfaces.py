"""Required interfaces for k8s clients."""

from __future__ import annotations

from collections.abc import AsyncIterable
from typing import Any, Protocol

from kubernetes_asyncio.client import V1DeleteOptions, V1PriorityClass, V1ResourceQuota

from renku_data_services.k8s.models import K8sObject, K8sObjectFilter, K8sObjectMeta, K8sSecret


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

    async def create_secret(self, secret: K8sSecret) -> K8sSecret:
        """Create a secret."""
        ...

    async def patch_secret(self, secret: K8sObjectMeta, patch: dict[str, Any] | list[dict[str, Any]]) -> K8sSecret:
        """Patch an existing secret."""
        ...

    async def delete_secret(self, secret: K8sObjectMeta) -> None:
        """Delete a secret."""
        ...

    # async def create_or_patch_secret(self, secret: K8sSecret) -> K8sSecret:
    #     """Create or patch a secret.

    #     This is equivalent to an upsert operation.
    #     """
    #     logger = logging.getLogger(SecretClient.__name__)

    #     result = await self.create_secret(secret)
    #     # TODO: handle kr8s._exceptions.ServerError: secrets "flora-thieba-65c0e15c0a35" already exists
    #     if result.manifest.to_json() != secret.manifest.to_json():
    #         logger.warning(f"The secret {secret.namespace}/{secret.name} needs to be patched!")
    #         logger.warning(f"result = {result.manifest.to_json()}")
    #         logger.warning(f"secret = {secret.manifest.to_json()}")
    #         logger.warning(f"secret.manifest.stringData = {secret.manifest.get("stringData")}")
    #         result = await self.patch_secret(secret, secret.to_patch())
    #     return result


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


class K8sClient(Protocol):
    """Methods to manipulate resources on a Kubernetes cluster."""

    async def create(self, obj: K8sObject, refresh: bool) -> K8sObject:
        """Create the k8s object."""
        ...

    async def patch(self, meta: K8sObjectMeta, patch: dict[str, Any] | list[dict[str, Any]]) -> K8sObject:
        """Patch a k8s object.

        If the patch is a list we assume that we have a rfc6902 json patch like
        `[{ "op": "add", "path": "/a/b/c", "value": [ "foo", "bar" ] }]`.
        If the patch is a dictionary then it is considered to be a rfc7386 json merge patch.
        """
        ...

    async def delete(self, meta: K8sObjectMeta) -> None:
        """Delete a k8s object."""
        ...

    async def get(self, meta: K8sObjectMeta) -> K8sObject | None:
        """Get a specific k8s object, None is returned if the object does not exist."""
        ...

    def list(self, _filter: K8sObjectFilter) -> AsyncIterable[K8sObject]:
        """List all k8s objects."""
        ...
