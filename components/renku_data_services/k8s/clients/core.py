"""Kubernetes Library wrappers."""

from __future__ import annotations

import os
from collections.abc import AsyncIterable, Callable

from renku_data_services.errors import errors
from renku_data_services.k8s.constants import ClusterId
from renku_data_services.k8s.core import ClusterConnection, DeletePropagationPolicy, K8sClient, K8sClusterClient
from renku_data_services.k8s.models import K8sObject, K8sObjectFilter, K8sObjectMeta, K8sPatches


class K8sClusterClientsPool(K8sClient):
    """A wrapper around a pool of kr8s k8s clients."""

    def __init__(self, clusters: Callable[[], AsyncIterable[K8sClusterClient]]) -> None:
        self.__clusters = clusters
        self.__clients: dict[ClusterId, K8sClusterClient] = {}

    async def __init_clients_if_needed(self) -> None:
        if len(self.__clients) > 0 and os.environ.get("ALWAYS_READ_CLUSTERS") is None:
            return
        async for cluster in self.__clusters():
            self.__clients[cluster.get_cluster().id] = cluster

    async def __get_client_or_die(self, cluster_id: ClusterId) -> K8sClusterClient:
        await self.__init_clients_if_needed()
        cluster_client = self.__clients.get(cluster_id)

        if cluster_client is None:
            raise errors.MissingResourceError(
                message=f"Could not find cluster with id {cluster_id} in the list of clusters."
            )
        return cluster_client

    async def cluster_by_id(self, cluster_id: ClusterId) -> ClusterConnection:
        """Return a cluster by its id."""
        client = await self.__get_client_or_die(cluster_id)
        return client.get_cluster()

    async def create(self, obj: K8sObject, refresh: bool) -> K8sObject:
        """Create the k8s object."""
        client = await self.__get_client_or_die(obj.cluster)
        return await client.create(obj, refresh)

    async def patch(self, meta: K8sObjectMeta, patch: K8sPatches) -> K8sObject:
        """Patch a k8s object."""
        client = await self.__get_client_or_die(meta.cluster)
        return await client.patch(meta, patch)

    async def delete(
        self, meta: K8sObjectMeta, propagation_policy: DeletePropagationPolicy = DeletePropagationPolicy.foreground
    ) -> None:
        """Delete a k8s object."""
        client = await self.__get_client_or_die(meta.cluster)
        await client.delete(meta, propagation_policy)

    async def get(self, meta: K8sObjectMeta) -> K8sObject | None:
        """Get a specific k8s object, None is returned if the object does not exist."""
        client = await self.__get_client_or_die(meta.cluster)
        return await client.get(meta)

    async def list(self, _filter: K8sObjectFilter) -> AsyncIterable[K8sObject]:
        """List all k8s objects."""
        await self.__init_clients_if_needed()
        cluster_clients = sorted(list(self.__clients.values()))
        for c in cluster_clients:
            async for r in c.list(_filter):
                yield r
