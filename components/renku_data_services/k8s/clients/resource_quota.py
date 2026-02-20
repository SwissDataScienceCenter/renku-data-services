"""Kubernetes ResourceQuota wrappers."""

from __future__ import annotations

from collections.abc import AsyncIterable
from typing import Protocol

from box import Box

from renku_data_services.errors import errors
from renku_data_services.k8s.clients.core import K8sClusterClientsPool
from renku_data_services.k8s.constants import ClusterId
from renku_data_services.k8s.models import GVK, K8sObject, K8sObjectFilter, K8sObjectMeta, K8sPatch, K8sPatches


class K8sResourceQuota(K8sObject):
    """Represents a ResourceQuota in k8s."""

    def __init__(
        self,
        name: str,
        namespace: str,
        cluster: ClusterId,
        manifest: Box,
    ) -> None:
        super().__init__(
            name=name,
            namespace=namespace,
            cluster=cluster,
            gvk=GVK(kind="ResourceQuota", version="v1"),
            manifest=manifest,
        )

    @classmethod
    def meta(cls, name: str, namespace: str, cluster_id: ClusterId) -> K8sObjectMeta:
        """Return a K8sObjectMeta describing the named resource quota."""
        return K8sObjectMeta(
            name=name,
            namespace=namespace,
            cluster=cluster_id,
            gvk=GVK(kind="ResourceQuota", version="v1"),
        )

    @classmethod
    def get_filter(cls, label_selector: dict[str, str], namespace: str, cluster_id: ClusterId) -> K8sObjectFilter:
        """Return a filter to list K8s objects."""
        return K8sObjectFilter(
            gvk=GVK(kind="ResourceQuota", version="v1"),
            namespace=namespace,
            label_selector=label_selector,
            cluster=cluster_id,
        )

    @classmethod
    def from_k8s_object(cls, k8s_object: K8sObject) -> K8sResourceQuota:
        """Convert a k8s object to a K8sResourceQuota object."""
        assert k8s_object.namespace is not None

        return K8sResourceQuota(
            name=k8s_object.name,
            namespace=k8s_object.namespace,
            cluster=k8s_object.cluster,
            manifest=k8s_object.manifest,
        )

    @classmethod
    def from_patch(cls, patch: K8sPatch, namespace: str, cluster_id: ClusterId) -> K8sResourceQuota:
        """Convert a valid K8sPatch to K8sResourceQuota."""
        name = patch["metadata"]["name"]
        patch["metadata"]["namespace"] = namespace
        return K8sResourceQuota(name=name, namespace=namespace, cluster=cluster_id, manifest=Box(patch))


class ResourceQuotaClient(Protocol):
    """Methods to manipulate ResourceQuota kubernetes resources."""

    def list_resource_quota(
        self, label_selector: dict[str, str], cluster_id: ClusterId
    ) -> AsyncIterable[K8sResourceQuota]:
        """List resource quotas."""
        ...

    async def read_resource_quota(self, name: str, cluster_id: ClusterId) -> K8sResourceQuota:
        """Get a resource quota."""
        ...

    async def create_resource_quota(self, quota: K8sPatch, cluster_id: ClusterId) -> K8sResourceQuota:
        """Create a resource quota."""
        ...

    async def delete_resource_quota(self, name: str, cluster_id: ClusterId) -> None:
        """Delete a resource quota."""
        ...

    async def patch_resource_quota(self, name: str, patch: K8sPatches, cluster_id: ClusterId) -> K8sResourceQuota:
        """Update a resource quota."""
        ...


class K8sResourceQuotaClient(ResourceQuotaClient):
    """Real k8s core API client that exposes the required functions."""

    def __init__(self, k8s_client: K8sClusterClientsPool) -> None:
        self.__client = k8s_client

    async def __cluster_namespace(self, cluster_id: ClusterId) -> str:
        return (await self.__client.cluster_by_id(cluster_id)).namespace

    async def read_resource_quota(self, name: str, cluster_id: ClusterId) -> K8sResourceQuota:
        """Get a resource quota."""
        namespace = await self.__cluster_namespace(cluster_id)
        res = await self.__client.get(K8sResourceQuota.meta(name, namespace, cluster_id))
        if res is None:
            raise errors.MissingResourceError(message=f"The resource quota {namespace}/{name} cannot be found.")
        return K8sResourceQuota.from_k8s_object(res)

    async def list_resource_quota(
        self, label_selector: dict[str, str], cluster_id: ClusterId
    ) -> AsyncIterable[K8sResourceQuota]:
        """List resource quotas."""
        namespace = await self.__cluster_namespace(cluster_id)
        quotas = self.__client.list(K8sResourceQuota.get_filter(label_selector, namespace, cluster_id))
        async for quota in quotas:
            yield K8sResourceQuota.from_k8s_object(quota)

    async def create_resource_quota(self, quota: K8sPatch, cluster_id: ClusterId) -> K8sResourceQuota:
        """Create a resource quota."""
        res = await self.__client.create(
            K8sResourceQuota.from_patch(quota, await self.__cluster_namespace(cluster_id), cluster_id), False
        )
        return K8sResourceQuota.from_k8s_object(res)

    async def delete_resource_quota(self, name: str, cluster_id: ClusterId) -> None:
        """Delete a resource quota."""
        namespace = await self.__cluster_namespace(cluster_id)
        await self.__client.delete(K8sResourceQuota.meta(name, namespace, cluster_id))

    async def patch_resource_quota(self, name: str, patch: K8sPatches, cluster_id: ClusterId) -> K8sResourceQuota:
        """Update a resource quota."""
        namespace = await self.__cluster_namespace(cluster_id)
        res = await self.__client.patch(K8sResourceQuota.meta(name, namespace, cluster_id), patch)
        return K8sResourceQuota.from_k8s_object(res)


class DummyResourceQuotaClient(ResourceQuotaClient):
    """Dummy k8s core API client that does not require a k8s cluster.

    Not suitable for production - to be used only for testing and development.
    """

    async def read_resource_quota(self, name: str, cluster_id: ClusterId) -> K8sResourceQuota:
        """Get a resource quota."""
        raise NotImplementedError()

    def list_resource_quota(
        self, label_selector: dict[str, str], cluster_id: ClusterId
    ) -> AsyncIterable[K8sResourceQuota]:
        """List resource quotas."""
        raise NotImplementedError()

    async def create_resource_quota(self, quota: K8sPatch, cluster_id: ClusterId) -> K8sResourceQuota:
        """Create a resource quota."""
        raise NotImplementedError()

    async def delete_resource_quota(self, name: str, cluster_id: ClusterId) -> None:
        """Delete a resource quota."""
        raise NotImplementedError()

    async def patch_resource_quota(self, name: str, patch: K8sPatches, cluster_id: ClusterId) -> K8sResourceQuota:
        """Update a resource quota."""
        raise NotImplementedError()
