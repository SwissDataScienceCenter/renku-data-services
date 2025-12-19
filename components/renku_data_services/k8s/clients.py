"""Different implementations of k8s clients."""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterable
from copy import deepcopy
from typing import Any, overload

import kr8s
from box import Box
from kubernetes import client

from renku_data_services.errors import errors
from renku_data_services.k8s.client_interfaces import K8sClient, PriorityClassClient, ResourceQuotaClient, SecretClient
from renku_data_services.k8s.constants import ClusterId
from renku_data_services.k8s.db import K8sDbCache
from renku_data_services.k8s.models import (
    GVK,
    APIObjectInCluster,
    ClusterConnection,
    ClusterScopedK8sObject,
    DeletePropagationPolicy,
    K8sObject,
    K8sObjectFilter,
    K8sObjectMeta,
    K8sSecret,
)


class K8sResourceQuotaClient(ResourceQuotaClient):
    """Real k8s core API client that exposes the required functions."""

    def __init__(self, k8s_client: K8sClient) -> None:
        self.__client = k8s_client
        self.__quota_gvk = GVK(kind="ResourceQuota", version="v1")
        self.__converter = client.ApiClient()

    def _meta(self, name: str, namespace: str, cluster_id: ClusterId) -> K8sObjectMeta:
        return K8sObjectMeta(
            name=name,
            namespace=namespace,
            gvk=self.__quota_gvk,
            cluster=cluster_id,
        )

    def _convert(self, data: Box) -> client.V1ResourceQuota:
        # NOTE: There is unfortunately no other way around this, this is the only thing that will
        # properly handle snake case - camel case conversions and a bunch of other things.
        output = self.__converter._ApiClient__deserialize(data.to_dict(), client.V1ResourceQuota)
        if not isinstance(output, client.V1ResourceQuota):
            raise errors.ProgrammingError(message="Could not convert the output from kr8s to a ResourceQuota")
        return output

    async def read_resource_quota(self, name: str, namespace: str, cluster_id: ClusterId) -> client.V1ResourceQuota:
        """Get a resource quota."""
        res = await self.__client.get(self._meta(name, namespace, cluster_id))
        if res is None:
            raise errors.MissingResourceError(message=f"The resource quota {namespace}/{name} cannot be found.")
        return self._convert(res.manifest)

    async def list_resource_quota(
        self, namespace: str, label_selector: dict[str, str], cluster_id: ClusterId
    ) -> AsyncIterable[client.V1ResourceQuota]:
        """List resource quotas."""
        filter = K8sObjectFilter(
            gvk=self.__quota_gvk,
            namespace=namespace,
            label_selector=label_selector,
            cluster=cluster_id,
        )
        quotas = self.__client.list(filter)
        async for quota in quotas:
            yield self._convert(quota.manifest)

    async def create_resource_quota(self, namespace: str, body: client.V1ResourceQuota, cluster_id: ClusterId) -> None:
        """Create a resource quota."""
        obj = K8sObject(
            name=body.metadata.name,
            namespace=namespace,
            gvk=self.__quota_gvk,
            manifest=Box(self.__converter.sanitize_for_serialization(body)),
            cluster=cluster_id,
        )
        await self.__client.create(obj, False)

    async def delete_resource_quota(self, name: str, namespace: str, cluster_id: ClusterId) -> None:
        """Delete a resource quota."""
        await self.__client.delete(self._meta(name, namespace, cluster_id))

    async def patch_resource_quota(
        self, name: str, namespace: str, body: client.V1ResourceQuota, cluster_id: ClusterId
    ) -> None:
        """Update a resource quota."""
        patch = self.__converter.sanitize_for_serialization(body)
        await self.__client.patch(self._meta(name, namespace, cluster_id), patch)


class K8sSecretClient(SecretClient):
    """A wrapper around a kr8s k8s client, acts on Secrets."""

    def __init__(self, client: K8sClient) -> None:
        self.__client = client

    async def create_secret(self, secret: K8sSecret) -> K8sSecret:
        """Create a secret."""

        return K8sSecret.from_k8s_object(await self.__client.create(secret, False))

    async def patch_secret(self, secret: K8sObjectMeta, patch: dict[str, Any] | list[dict[str, Any]]) -> K8sSecret:
        """Patch a secret."""

        return K8sSecret.from_k8s_object(await self.__client.patch(secret, patch))

    async def delete_secret(self, secret: K8sObjectMeta) -> None:
        """Delete a secret."""

        await self.__client.delete(secret)


class K8sSchedulingClient(PriorityClassClient):
    """Real k8s scheduling API client that exposes the required functions."""

    def __init__(self, k8s_client: K8sClient) -> None:
        self.__client = k8s_client
        self.__pc_gvk = GVK(kind="PriorityClass", version="v1", group="scheduling.k8s.io")
        self.__converter = client.ApiClient()

    def _meta(self, name: str, cluster_id: ClusterId) -> K8sObjectMeta:
        return K8sObjectMeta(
            name=name,
            namespace=None,
            gvk=self.__pc_gvk,
            cluster=cluster_id,
        )

    def _convert(self, data: Box) -> client.V1PriorityClass:
        # NOTE: There is unfortunately no other way around this, this is the only thing that will
        # properly handle snake case - camel case conversions and a bunch of other things.
        output = self.__converter._ApiClient__deserialize(data.to_dict(), client.V1PriorityClass)
        if not isinstance(output, client.V1PriorityClass):
            raise errors.ProgrammingError(message="Could not convert the output from kr8s to a PriorityClass")
        return output

    async def create_priority_class(
        self, body: client.V1PriorityClass, cluster_id: ClusterId
    ) -> client.V1PriorityClass:
        """Create a priority class."""
        obj = ClusterScopedK8sObject(
            name=body.metadata.name,
            gvk=self.__pc_gvk,
            manifest=Box(self.__converter.sanitize_for_serialization(body)),
            cluster=cluster_id,
        )
        output = await self.__client.create(obj, refresh=True)
        return self._convert(output.manifest)

    async def delete_priority_class(
        self,
        name: str,
        cluster_id: ClusterId,
        propagation_policy: DeletePropagationPolicy = DeletePropagationPolicy.foreground,
    ) -> None:
        """Delete a priority class."""
        metadata = self._meta(name, cluster_id)
        await self.__client.delete(metadata, propagation_policy)

    async def read_priority_class(self, name: str, cluster_id: ClusterId) -> client.V1PriorityClass | None:
        """Get a priority class."""
        metadata = self._meta(name, cluster_id)
        output = await self.__client.get(metadata)
        if not output:
            return None
        return self._convert(output.manifest)


class DummyCoreClient(ResourceQuotaClient, SecretClient):
    """Dummy k8s core API client that does not require a k8s cluster.

    Not suitable for production - to be used only for testing and development.
    """

    async def read_resource_quota(self, name: str, namespace: str, cluster_id: ClusterId) -> client.V1ResourceQuota:
        """Get a resource quota."""
        raise NotImplementedError()

    def list_resource_quota(
        self, namespace: str, label_selector: dict[str, str], cluster_id: ClusterId
    ) -> AsyncIterable[client.V1ResourceQuota]:
        """List resource quotas."""
        raise NotImplementedError()

    async def create_resource_quota(self, namespace: str, body: client.V1ResourceQuota, cluster_id: ClusterId) -> None:
        """Create a resource quota."""
        raise NotImplementedError()

    async def delete_resource_quota(self, name: str, namespace: str, cluster_id: ClusterId) -> None:
        """Delete a resource quota."""
        raise NotImplementedError()

    async def patch_resource_quota(
        self, name: str, namespace: str, body: client.V1ResourceQuota, cluster_id: ClusterId
    ) -> None:
        """Update a resource quota."""
        raise NotImplementedError()

    async def create_secret(self, secret: K8sSecret) -> K8sSecret:
        """Create a secret."""
        raise NotImplementedError()

    async def patch_secret(self, secret: K8sObjectMeta, patch: dict[str, Any] | list[dict[str, Any]]) -> K8sSecret:
        """Patch a secret."""
        raise NotImplementedError()

    async def delete_secret(self, secret: K8sObjectMeta) -> None:
        """Delete a secret."""
        raise NotImplementedError()


class DummySchedulingClient(PriorityClassClient):
    """Dummy k8s scheduling API client that does not require a k8s cluster.

    Not suitable for production - to be used only for testing and development.
    """

    async def create_priority_class(
        self, body: client.V1PriorityClass, cluster_id: ClusterId
    ) -> client.V1PriorityClass:
        """Create a priority class."""
        raise NotImplementedError()

    async def read_priority_class(self, name: str, cluster_id: ClusterId) -> client.V1PriorityClass | None:
        """Get a priority class."""
        raise NotImplementedError()

    async def delete_priority_class(
        self,
        name: str,
        cluster_id: ClusterId,
        propagation_policy: DeletePropagationPolicy = DeletePropagationPolicy.foreground,
    ) -> None:
        """Delete a priority class."""
        raise NotImplementedError()


class K8sClusterClient(K8sClient):
    """A wrapper around a kr8s k8s client, acts on all resources of a cluster."""

    def __init__(self, cluster: ClusterConnection) -> None:
        self.__cluster = cluster
        assert self.__cluster.api is not None

    def __lt__(self, other: K8sClusterClient) -> bool:
        """Allows for sorting."""
        return self.__cluster.id < other.__cluster.id and self.__cluster.namespace < other.__cluster.namespace

    def get_cluster(self) -> ClusterConnection:
        """Return a cluster object."""
        return self.__cluster

    async def __list(self, _filter: K8sObjectFilter) -> AsyncIterable[APIObjectInCluster]:
        if _filter.cluster is not None and _filter.cluster != self.__cluster.id:
            return

        names = [_filter.name] if _filter.name is not None else []

        try:
            res = self.__cluster.api.async_get(
                _filter.gvk.kr8s_kind,
                *names,
                label_selector=_filter.label_selector,
                namespace=_filter.namespace,
            )

            async for r in res:
                yield APIObjectInCluster(r, self.__cluster.id)

        except (kr8s.ServerError, kr8s.APITimeoutError, ValueError) as _e:
            # ValueError is generated when the kind does not exist on the cluster
            return

    async def __get_api_object(self, meta: K8sObjectFilter) -> APIObjectInCluster | None:
        return await anext(aiter(self.__list(meta)), None)

    @overload
    async def create(self, obj: K8sObject, refresh: bool) -> K8sObject: ...
    @overload
    async def create(self, obj: ClusterScopedK8sObject, refresh: bool) -> ClusterScopedK8sObject: ...
    async def create(
        self, obj: K8sObject | ClusterScopedK8sObject, refresh: bool
    ) -> K8sObject | ClusterScopedK8sObject:
        """Create the k8s object."""

        api_obj = obj.to_api_object(self.__cluster.api)
        await api_obj.create()

        # In some cases the service account does not have read rights, in which case we cannot call get(), and refresh()
        if refresh:
            # if refresh isn't called, status and timestamp will be blank
            await api_obj.refresh()

        return obj.with_manifest(api_obj.to_dict())

    async def patch(self, meta: K8sObjectMeta, patch: dict[str, Any] | list[dict[str, Any]]) -> K8sObject:
        """Patch a k8s object.

        If the patch is a list we assume that we have a rfc6902 json patch like
        `[{ "op": "add", "path": "/a/b/c", "value": [ "foo", "bar" ] }]`.
        If the patch is a dictionary then it is considered to be a rfc7386 json merge patch.
        """
        obj = await self.__get_api_object(meta.to_filter())
        if obj is None:
            raise errors.MissingResourceError(message=f"The k8s resource with metadata {meta} cannot be found.")
        patch_type = "json" if isinstance(patch, list) else None
        await obj.obj.patch(patch, type=patch_type)
        await obj.obj.refresh()

        return meta.with_manifest(obj.obj.to_dict())

    async def delete(
        self, meta: K8sObjectMeta, propagation_policy: DeletePropagationPolicy = DeletePropagationPolicy.foreground
    ) -> None:
        """Delete a k8s object."""
        obj = await self.__get_api_object(meta.to_filter())
        if obj is None:
            return
        with contextlib.suppress(kr8s.NotFoundError):
            await obj.obj.delete(propagation_policy=propagation_policy.value)

    async def get(self, meta: K8sObjectMeta) -> K8sObject | None:
        """Get a specific k8s object, None is returned if the object does not exist."""
        obj = await self.__get_api_object(meta.to_filter())
        if obj is None:
            return None
        return meta.with_manifest(obj.obj.to_dict())

    async def list(self, _filter: K8sObjectFilter) -> AsyncIterable[K8sObject]:
        """List all k8s objects."""
        async for r in self.__list(_filter):
            yield r.to_k8s_object()


class K8sCachedClusterClient(K8sClusterClient):
    """A wrapper around a kr8s k8s client.

    Provides access to a cache for listing and reading resources but fallback to the cluster for other operations.
    """

    def __init__(self, cluster: ClusterConnection, cache: K8sDbCache, kinds_to_cache: list[GVK]) -> None:
        super().__init__(cluster)
        self.__cache = cache
        self.__kinds_to_cache = set(kinds_to_cache)

    @overload
    async def create(self, obj: K8sObject, refresh: bool) -> K8sObject: ...
    @overload
    async def create(self, obj: ClusterScopedK8sObject, refresh: bool) -> ClusterScopedK8sObject: ...
    async def create(
        self, obj: K8sObject | ClusterScopedK8sObject, refresh: bool
    ) -> K8sObject | ClusterScopedK8sObject:
        """Create the k8s object."""
        if obj.gvk in self.__kinds_to_cache:
            if isinstance(obj, ClusterScopedK8sObject):
                raise NotImplementedError("Caching of cluster scoped K8s resources is not supported")
            await self.__cache.upsert(obj)
        try:
            obj = await super().create(obj, refresh)
        except:
            # if there was an error creating the k8s object, we delete it from the db again to not have ghost entries
            if obj.gvk in self.__kinds_to_cache:
                await self.__cache.delete(obj)
            raise
        return obj

    async def patch(self, meta: K8sObjectMeta, patch: dict[str, Any] | list[dict[str, Any]]) -> K8sObject:
        """Patch a k8s object."""
        obj = await super().patch(meta, patch)
        if meta.gvk in self.__kinds_to_cache:
            await self.__cache.upsert(obj)
        return obj

    async def delete(
        self, meta: K8sObjectMeta, propagation_policy: DeletePropagationPolicy = DeletePropagationPolicy.foreground
    ) -> None:
        """Delete a k8s object."""
        await super().delete(meta, propagation_policy)
        # NOTE: We use foreground deletion in the k8s client.
        # This means that the parent resource is usually not deleted immediately and will
        # wait for its children to be deleted before it is deleted.
        # To avoid premature purging of resources from the cache we do not delete the resource here
        # from the cache, rather we expect that the cache will sync itself properly and quickly purge
        # stale resources.

    async def get(self, meta: K8sObjectMeta) -> K8sObject | None:
        """Get a specific k8s object, None is returned if the object does not exist."""
        if meta.gvk in self.__kinds_to_cache:
            res = await self.__cache.get(meta)
        else:
            res = await super().get(meta)

        return res

    async def list(self, _filter: K8sObjectFilter) -> AsyncIterable[K8sObject]:
        """List all k8s objects."""

        # Don't even go to the DB or Kubernetes if the cluster id is set and does not match our cluster.
        if _filter.cluster is not None and _filter.cluster != self.get_cluster().id:
            return

        filter2 = deepcopy(_filter)
        if filter2.cluster is None:
            filter2.cluster = self.get_cluster().id

        results = self.__cache.list(filter2) if _filter.gvk in self.__kinds_to_cache else super().list(filter2)
        async for res in results:
            yield res


class K8sClusterClientsPool(K8sClient):
    """A wrapper around a pool of kr8s k8s clients."""

    def __init__(self, clusters: AsyncIterable[K8sClusterClient]) -> None:
        self.__clusters = clusters
        self.__clients: dict[ClusterId, K8sClusterClient] = {}

    async def __init_clients_if_needed(self) -> None:
        if len(self.__clients) > 0:
            return
        async for cluster in self.__clusters:
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

    @overload
    async def create(self, obj: K8sObject, refresh: bool) -> K8sObject: ...
    @overload
    async def create(self, obj: ClusterScopedK8sObject, refresh: bool) -> ClusterScopedK8sObject: ...
    async def create(
        self, obj: K8sObject | ClusterScopedK8sObject, refresh: bool
    ) -> K8sObject | ClusterScopedK8sObject:
        """Create the k8s object."""
        client = await self.__get_client_or_die(obj.cluster)
        return await client.create(obj, refresh)

    async def patch(self, meta: K8sObjectMeta, patch: dict[str, Any] | list[dict[str, Any]]) -> K8sObject:
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
