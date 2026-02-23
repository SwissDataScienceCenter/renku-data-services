"""Base Kubernetes Library wrappers."""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterable
from copy import deepcopy
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, Self, cast

import kr8s
from box import Box
from kr8s import APIObject
from kr8s._api import Api
from kubernetes import client

from renku_data_services.errors import errors
from renku_data_services.k8s.constants import DUMMY_TASK_RUN_USER_ID, ClusterId
from renku_data_services.k8s.db import K8sDbCache
from renku_data_services.k8s.models import GVK, K8sObject, K8sObjectFilter, K8sObjectMeta, K8sPatches

_kubernetes_client = client.ApiClient()
sanitizer = _kubernetes_client.sanitize_for_serialization


class DeletePropagationPolicy(StrEnum):
    """Propagation policy when deleting objects in K8s."""

    foreground = "Foreground"
    background = "Background"


class K8sClient(Protocol):
    """Methods to manipulate resources on a Kubernetes cluster."""

    async def create(self, obj: K8sObject, refresh: bool) -> K8sObject:
        """Create the k8s object."""
        ...

    async def patch(self, meta: K8sObjectMeta, patch: K8sPatches) -> K8sObject:
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


@dataclass
class APIObjectInCluster:
    """A kr8s k8s object from a specific cluster."""

    obj: APIObject
    cluster: ClusterId

    @property
    def user_id(self) -> str | None:
        """Extract the user id from annotations."""
        labels = cast(dict[str, str], self.obj.metadata.get("labels", {}))
        match self.obj.singular:
            case "jupyterserver":
                return labels.get("renku.io/userId", None)
            case "amaltheasession":
                return labels.get("renku.io/safe-username", None)
            case "buildrun":
                return labels.get("renku.io/safe-username", None)
            case "taskrun":
                return DUMMY_TASK_RUN_USER_ID
            case _:
                return None

    @property
    def meta(self) -> K8sObjectMeta:
        """Extract the metadata from an api object."""
        return K8sObjectMeta(
            name=self.obj.name,
            namespace=self.obj.namespace or "default",
            cluster=self.cluster,
            gvk=GVK.from_kr8s_object(self.obj),
            user_id=self.user_id,
        )

    def to_k8s_object(self) -> K8sObject:
        """Convert the api object to a regular k8s object."""
        if self.obj.name is None or self.obj.namespace is None:
            raise errors.ProgrammingError()
        return K8sObject(
            name=self.obj.name,
            namespace=self.obj.namespace,
            gvk=GVK.from_kr8s_object(self.obj),
            manifest=Box(self.obj.to_dict()),
            cluster=self.cluster,
            user_id=self.user_id,
        )

    @classmethod
    def from_k8s_object(cls, obj: K8sObject, api: Api) -> Self:
        """Convert a regular k8s object to an api object."""

        return cls(
            obj=obj.to_api_object(api),
            cluster=obj.cluster,
        )


@dataclass(frozen=True, eq=True, kw_only=True)
class ClusterConnection:
    """K8s Cluster wrapper."""

    id: ClusterId
    namespace: str
    api: Api

    def with_api_object(self, obj: APIObject) -> APIObjectInCluster:
        """Create an API object associated with the cluster."""
        return APIObjectInCluster(obj, self.id)


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

    async def create(self, obj: K8sObject, refresh: bool) -> K8sObject:
        """Create the k8s object, scoped or not."""
        api_obj = obj.to_api_object(self.__cluster.api)
        await api_obj.create()

        # In some cases the service account does not have read rights, in which case we cannot call get(), and refresh()
        if refresh:
            # if refresh isn't called, status and timestamp will be blank
            await api_obj.refresh()
        return obj.with_manifest(api_obj.to_dict())

    async def patch(self, meta: K8sObjectMeta, patch: K8sPatches) -> K8sObject:
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

    async def create(self, obj: K8sObject, refresh: bool) -> K8sObject:
        """Create the k8s object."""
        if obj.gvk in self.__kinds_to_cache:
            if not obj.namespaced():
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

    async def patch(self, meta: K8sObjectMeta, patch: K8sPatches) -> K8sObject:
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
