"""Different implementations of k8s clients."""

from __future__ import annotations

import contextlib
import multiprocessing.synchronize
from collections.abc import AsyncIterable
from copy import deepcopy
from multiprocessing import Lock
from multiprocessing.synchronize import Lock as LockType
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import kr8s
from kubernetes import client, config
from kubernetes.config.config_exception import ConfigException
from kubernetes.config.incluster_config import SERVICE_CERT_FILENAME, SERVICE_TOKEN_FILENAME, InClusterConfigLoader

from renku_data_services.errors import errors
from renku_data_services.k8s.client_interfaces import K8sCoreClientInterface, K8sSchedudlingClientInterface

if TYPE_CHECKING:
    from renku_data_services.k8s.models import (
        GVK,
        APIObjectInCluster,
        Cluster,
        ClusterId,
        K8sObject,
        K8sObjectFilter,
        K8sObjectMeta,
    )
    from renku_data_services.k8s_watcher import K8sDbCache


class K8sCoreClient(K8sCoreClientInterface):  # pragma:nocover
    """Real k8s core API client that exposes the required functions."""

    def __init__(self) -> None:
        try:
            InClusterConfigLoader(
                token_filename=SERVICE_TOKEN_FILENAME,
                cert_filename=SERVICE_CERT_FILENAME,
            ).load_and_set()
        except ConfigException:
            config.load_config()
        self.client = client.CoreV1Api()

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

    def __init__(self) -> None:
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


class K8sClusterClient:
    """A wrapper around a kr8s k8s client, acts on all resources of a cluster."""

    def __init__(self, cluster: Cluster) -> None:
        self.__cluster = cluster
        assert self.__cluster.api is not None

    def get_cluster(self) -> Cluster:
        """Return a cluster object."""
        return self.__cluster

    async def __list(self, _filter: K8sObjectFilter) -> AsyncIterable[APIObjectInCluster]:
        if _filter.cluster is not None and _filter.cluster != self.__cluster.id:
            return
        if _filter.namespace is not None and _filter.namespace != self.__cluster.namespace:
            return
        names = [_filter.name] if _filter.name is not None else []

        try:
            res = await self.__cluster.api.async_get(
                _filter.gvk.kr8s_kind,
                *names,
                label_selector=_filter.label_selector,
                namespace=_filter.namespace,
            )
        except (kr8s.ServerError, kr8s.APITimeoutError):
            return

        if not isinstance(res, list):
            res = [res]
        for r in res:
            yield self.__cluster.with_api_object(r)

    async def __get_api_object(self, meta: K8sObjectFilter) -> APIObjectInCluster | None:
        return await anext(aiter(self.__list(meta)), None)

    async def create(self, obj: K8sObject) -> K8sObject:
        """Create the k8s object."""

        api_obj = obj.to_api_object(self.__cluster.api)
        await api_obj.create()
        # if refresh isn't called, status and timestamp will be blank
        await api_obj.refresh()
        return obj.meta.with_manifest(api_obj.to_dict())

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

    async def delete(self, meta: K8sObjectMeta) -> None:
        """Delete a k8s object."""
        obj = await self.__get_api_object(meta.to_filter())
        if obj is None:
            return
        with contextlib.suppress(kr8s.NotFoundError):
            await obj.obj.delete(propagation_policy="Foreground")

    async def get(self, meta: K8sObjectMeta) -> K8sObject | None:
        """Get a specific k8s object, None is returned if the object does not exist."""
        obj = await self.__get_api_object(meta.to_filter())
        if obj is None:
            return None
        return meta.with_manifest(obj.obj.to_dict())

    async def list(self, _filter: K8sObjectFilter) -> AsyncIterable[K8sObject]:
        """List all k8s objects."""
        results = self.__list(_filter)
        async for r in results:
            yield r.to_k8s_object()


class K8SCachedClusterClient(K8sClusterClient):
    """A wrapper around a kr8s k8s client.

    Provides access to a cache for listing and reading resources but fallback to the cluster for other operations.
    """

    def __init__(self, cluster: Cluster, cache: K8sDbCache, kinds_to_cache: list[GVK]) -> None:
        super().__init__(cluster)
        self.__cache = cache
        self.__kinds_to_cache = set(kinds_to_cache)

    async def create(self, obj: K8sObject) -> K8sObject:
        """Create the k8s object."""
        if obj.meta.gvk in self.__kinds_to_cache:
            await self.__cache.upsert(obj)
        try:
            obj = await super().create(obj)
        except:
            # if there was an error creating the k8s object, we delete it from the db again to not have ghost entries
            if obj.meta.gvk in self.__kinds_to_cache:
                await self.__cache.delete(obj)
            raise
        return obj

    async def patch(self, meta: K8sObjectMeta, patch: dict[str, Any] | list[dict[str, Any]]) -> K8sObject:
        """Patch a k8s object."""
        obj = await super().patch(meta, patch)
        if meta.gvk in self.__kinds_to_cache:
            await self.__cache.upsert(obj)
        return obj

    async def delete(self, meta: K8sObjectMeta) -> None:
        """Delete a k8s object."""
        await super().delete(meta)
        if meta.gvk in self.__kinds_to_cache:
            await self.__cache.delete(meta)

    async def get(self, meta: K8sObjectMeta) -> K8sObject | None:
        """Get a specific k8s object, None is returned if the object does not exist."""
        if meta.gvk in self.__kinds_to_cache:
            res = await self.__cache.get(meta)
        else:
            res = await super().get(meta)

        return res

    async def list(self, _filter: K8sObjectFilter) -> AsyncIterable[K8sObject]:
        """List all k8s objects."""
        results = self.__cache.list(_filter) if _filter.gvk in self.__kinds_to_cache else super().list(_filter)
        async for res in results:
            yield res


class K8sClusterClientsPool:
    """A wrapper around a kr8s k8s client, acts on all resources over many clusters."""

    def __init__(self, clusters: list[Cluster], cache: K8sDbCache, kinds_to_cache: list[GVK]) -> None:
        self.__clients = {c.id: K8SCachedClusterClient(c, cache, kinds_to_cache) for c in clusters}

    def __get_client_or_die(self, cluster_id: ClusterId) -> K8sClusterClient:
        cluster_client = self.__clients.get(cluster_id)
        if cluster_client is None:
            raise errors.MissingResourceError(
                message=f"Could not find cluster with id {cluster_id} in the list of clusters."
            )
        return cluster_client

    def cluster_by_id(self, cluster_id: ClusterId) -> Cluster:
        """Return a cluster by its id."""
        return self.__get_client_or_die(cluster_id).get_cluster()

    async def create(self, obj: K8sObject) -> K8sObject:
        """Create the k8s object."""
        return await self.__get_client_or_die(obj.cluster).create(obj)

    async def patch(self, meta: K8sObjectMeta, patch: dict[str, Any] | list[dict[str, Any]]) -> K8sObject:
        """Patch a k8s object."""
        return await self.__get_client_or_die(meta.cluster).patch(meta, patch)

    async def delete(self, meta: K8sObjectMeta) -> None:
        """Delete a k8s object."""
        await self.__get_client_or_die(meta.cluster).delete(meta)

    async def get(
        self,
        meta: K8sObjectMeta,
    ) -> K8sObject | None:
        """Get a specific k8s object, None is returned if the object does not exist."""
        return await self.__get_client_or_die(meta.cluster).get(meta)

    async def list(self, _filter: K8sObjectFilter) -> AsyncIterable[K8sObject]:
        """List all k8s objects."""
        cluster_clients = [v for v in self.__clients.values()]
        for c in cluster_clients:
            async for r in c.list(_filter):
                yield r
