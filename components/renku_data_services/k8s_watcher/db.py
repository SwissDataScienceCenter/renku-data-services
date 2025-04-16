"""K8s watcher database and k8s wrappers."""

from __future__ import annotations

import contextlib
import logging
from collections.abc import AsyncIterable, Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Self, cast

import kr8s
import sqlalchemy
from box import Box
from kr8s.asyncio import Api
from kr8s.asyncio.objects import APIObject
from sqlalchemy import bindparam, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from renku_data_services.errors import errors
from renku_data_services.k8s_watcher.models import ClusterId, K8sObject, K8sObjectMeta, ListFilter
from renku_data_services.k8s_watcher.orm import K8sObjectORM


@dataclass(eq=True, frozen=True)
class Cluster:
    """Representation of a k8s cluster."""

    id: ClusterId
    namespace: str
    api: Api


@dataclass
class APIObjectInCluster:
    """An kr8s k8s object from a specific cluster."""

    obj: APIObject
    cluster: ClusterId

    @property
    def user_id(self) -> str | None:
        """Extract the user id from annotations."""
        user_id = user_id_from_api_object(self.obj)
        return user_id

    @property
    def meta(self) -> K8sObjectMeta:
        """Extract the metadata from an api object."""
        return K8sObjectMeta(
            name=self.obj.name,
            namespace=self.obj.namespace or "default",
            cluster=self.cluster,
            version=self.obj.version,
            kind=self.obj.kind,
            user_id=self.user_id,
        )

    def to_k8s_object(self) -> K8sObject:
        """Convert the api object to a regular k8s object."""
        if self.obj.name is None or self.obj.namespace is None:
            raise errors.ProgrammingError()
        return K8sObject(
            name=self.obj.name,
            namespace=self.obj.namespace,
            kind=self.obj.kind,
            version=self.obj.version,
            manifest=Box(self.obj.to_dict()),
            cluster=self.cluster,
            user_id=self.user_id,
        )

    @classmethod
    def from_k8s_object(cls, obj: K8sObject, api: Api | None = None) -> Self:
        """Convert a regular k8s object to an api object."""

        class _APIObj(APIObject):
            kind = obj.meta.kind
            version = obj.meta.version
            singular = obj.meta.singular
            plural = obj.meta.plural
            endpoint = obj.meta.plural
            namespaced = obj.meta.namespaced

        return cls(
            obj=_APIObj(
                resource=obj.manifest,
                namespace=obj.meta.namespace,
                api=api,
            ),
            cluster=obj.cluster,
        )


type EventHandler = Callable[[APIObjectInCluster], Awaitable[None]]


class K8sClient:
    """A wrapper around a kr8s k8s client, acts on all resources over many clusters."""

    def __init__(self, clusters: dict[ClusterId, Cluster]) -> None:
        self.__clusters = clusters

    def __get_cluster_or_die(self, cluster_id: ClusterId) -> Cluster:
        cluster = self.__clusters.get(cluster_id)
        if not cluster:
            raise errors.MissingResourceError(
                message=f"Could not find cluster with id {cluster_id} in the list of clusters."
            )
        return cluster

    async def create(self, obj: K8sObject) -> K8sObject:
        """Create the k8s object."""
        cluster = self.__get_cluster_or_die(obj.cluster)
        api_obj = APIObjectInCluster.from_k8s_object(obj, cluster.api)
        await api_obj.obj.create()
        return api_obj.meta.with_manifest(api_obj.obj.to_dict())

    async def patch(self, meta: K8sObjectMeta, patch: dict[str, Any] | list[dict[str, Any]]) -> K8sObject:
        """Patch a k8s object.

        If the patch is a list we assume that we have a rfc6902 json patch like
        `[{ "op": "add", "path": "/a/b/c", "value": [ "foo", "bar" ] }]`.
        If the patch is a dictionary then it is considered to be a rfc7386 json merge patch.
        """
        obj = await self._get(meta)
        if not obj:
            raise errors.MissingResourceError(message=f"The k8s resource with metadata {meta} cannot be found.")
        patch_type = "json" if isinstance(patch, list) else None
        await obj.obj.patch(patch, type=patch_type)
        return meta.with_manifest(obj.obj.to_dict())

    async def delete(self, meta: K8sObjectMeta) -> None:
        """Delete a k8s object."""
        obj = await self._get(meta)
        if not obj:
            return None
        with contextlib.suppress(kr8s.NotFoundError):
            await obj.obj.delete(propagation_policy="Foreground")

    async def _get(self, meta: K8sObjectMeta) -> APIObjectInCluster | None:
        return await anext(aiter(self.__list(meta.to_list_filter())), None)

    async def get(self, meta: K8sObjectMeta) -> K8sObject | None:
        """Get a specific k8s object, None is returned if the object does not exist."""
        obj = await self._get(meta)
        if not obj:
            return None
        return meta.with_manifest(obj.obj.to_dict())

    async def __list(self, filter: ListFilter) -> AsyncIterable[APIObjectInCluster]:
        clusters = list(self.__clusters.values())
        if filter.cluster:
            single_cluster = self.__clusters.get(filter.cluster)
            clusters = [single_cluster] if single_cluster else []
        for cluster in clusters:
            if filter.namespace is not None and filter.namespace != cluster.namespace:
                continue
            names = [filter.name] if filter.name else []

            try:
                res = await cluster.api.async_get(
                    filter.kind,
                    *names,
                    label_selector=filter.label_selector,
                    namespace=filter.namespace,
                )
            except (kr8s.ServerError, kr8s.APITimeoutError):
                continue

            if not isinstance(res, list):
                res = [res]
            for r in res:
                yield APIObjectInCluster(r, cluster.id)

    async def list(self, filter: ListFilter) -> AsyncIterable[K8sObject]:
        """List all k8s objects."""
        results = self.__list(filter)
        async for r in results:
            yield r.to_k8s_object()


class K8sDbCache:
    """Caching k8s objects in postgres."""

    def __init__(self, session_maker: Callable[..., AsyncSession]) -> None:
        self.__session_maker = session_maker

    async def __get(self, meta: K8sObjectMeta, session: AsyncSession) -> K8sObjectORM | None:
        stmt = (
            select(K8sObjectORM)
            .where(K8sObjectORM.name == meta.name)
            .where(K8sObjectORM.namespace == meta.namespace)
            .where(K8sObjectORM.cluster == meta.cluster)
            .where(K8sObjectORM.kind == meta.kind.lower())
            .where(K8sObjectORM.version == meta.version)
        )
        if meta.user_id is not None:
            stmt = stmt.where(K8sObjectORM.user_id == meta.user_id)
        logging.warn(f"getting resourceuu{meta}")

        obj_orm = await session.scalar(stmt)
        logging.warn(f"got resource from db: {obj_orm}")
        return obj_orm

    async def upsert(self, obj: K8sObject) -> None:
        """Insert or update an object in the cache."""
        if obj.user_id is None:
            raise errors.ValidationError(message="user_id is required to upsert k8s object.")
        async with self.__session_maker() as session, session.begin():
            obj_orm = await self.__get(obj.meta, session)
            if obj_orm is not None:
                obj_orm.manifest = obj.manifest
                await session.commit()
                await session.flush()
                return
            obj_orm = K8sObjectORM(
                name=obj.name,
                namespace=obj.namespace or "default",
                kind=obj.kind.lower(),
                version=obj.version,
                manifest=obj.manifest.to_dict(),
                cluster=obj.cluster,
                user_id=obj.user_id,
            )
            session.add(obj_orm)
            await session.commit()
            await session.flush()
            return

    async def delete(self, meta: K8sObjectMeta) -> None:
        """Delete an object from the cache."""
        async with self.__session_maker() as session, session.begin():
            obj_orm = await self.__get(meta, session)
            if obj_orm is None:
                return
            await session.delete(obj_orm)
            return

    async def get(self, meta: K8sObjectMeta) -> K8sObject | None:
        """Get a single object from the cache."""
        async with self.__session_maker() as session, session.begin():
            obj = await self.__get(meta, session)
            if not obj:
                return None
            return meta.with_manifest(obj.manifest)

    async def list(self, filter: ListFilter) -> AsyncIterable[K8sObject]:
        """List objects from the cache."""
        async with self.__session_maker() as session, session.begin():
            stmt = select(K8sObjectORM)
            if filter.name:
                stmt = stmt.where(K8sObjectORM.name == filter.name)
            if filter.namespace:
                stmt = stmt.where(K8sObjectORM.namespace == filter.namespace)
            if filter.cluster:
                stmt = stmt.where(K8sObjectORM.cluster == filter.cluster)
            if filter.kind:
                stmt = stmt.where(K8sObjectORM.kind == filter.kind.lower())
            if filter.version:
                stmt = stmt.where(K8sObjectORM.version == filter.version)
            if filter.user_id:
                stmt = stmt.where(K8sObjectORM.user_id == filter.user_id)
            if filter.label_selector:
                stmt = stmt.where(
                    # K8sObjectORM.manifest.comparator.contains({"metadata": {"labels": filter.label_selector}})
                    sqlalchemy.text("manifest -> 'metadata' -> 'labels' @> :labels").bindparams(
                        bindparam("labels", filter.label_selector, type_=JSONB)
                    )
                )
            async for res in await session.stream_scalars(stmt):
                yield res.dump()


class CachedK8sClient(K8sClient):
    """A wrapper around a kr8s k8s client.

    Provides access to a cache for listing and reading resources but fallback to the cluster for other operations.
    """

    def __init__(self, clusters: dict[ClusterId, Cluster], cache: K8sDbCache, kinds_to_cache: list[str]) -> None:
        super().__init__(clusters)
        self.cache = cache
        self.__kinds_to_cache = [k.lower() for k in kinds_to_cache]

    async def create(self, obj: K8sObject) -> K8sObject:
        """Create the k8s object."""
        if obj.meta.kind.lower() in self.__kinds_to_cache:
            await self.cache.upsert(obj)
        try:
            obj = await super().create(obj)
        except:
            # if there was an error creating the k8s object, we delete it from the db again to now have ghost entries
            if obj.meta.kind.lower() in self.__kinds_to_cache:
                await self.cache.delete(obj)
            raise
        return obj

    async def patch(self, meta: K8sObjectMeta, patch: dict[str, Any] | list[dict[str, Any]]) -> K8sObject:
        """Patch a k8s object."""
        obj = await super().patch(meta, patch)
        if meta.kind.lower() in self.__kinds_to_cache:
            await self.cache.upsert(obj)
        return obj

    async def delete(self, meta: K8sObjectMeta) -> None:
        """Delete a k8s object."""
        await super().delete(meta)
        if meta.kind.lower() in self.__kinds_to_cache:
            await self.cache.delete(meta)

    async def get(self, meta: K8sObjectMeta) -> K8sObject | None:
        """Get a specific k8s object, None is returned if the object does not exist."""
        if meta.kind.lower() in self.__kinds_to_cache:
            res = await self.cache.get(meta)
        else:
            res = await super().get(meta)
        if res is None:
            return None
        return res

    async def get_api_object(self, meta: K8sObjectMeta) -> APIObjectInCluster | None:
        """Get a kr8s object directly, bypassing the cache.

        Note: only use this if you actually need to do k8s operations.
        """
        res = await super()._get(meta)
        if res is None:
            return None
        return res

    async def list(self, filter: ListFilter) -> AsyncIterable[K8sObject]:
        """List all k8s objects."""
        results = self.cache.list(filter) if filter.kind.lower() in self.__kinds_to_cache else super().list(filter)
        async for res in results:
            yield res


def k8s_object_handler(cache: K8sDbCache) -> EventHandler:
    """Listens and to k8s events and updates the cache."""

    async def handler(obj: APIObjectInCluster) -> None:
        if obj.obj.metadata.get("deletionTimestamp"):
            # The object is being deleted
            await cache.delete(obj.meta)
            return
        k8s_object = obj.to_k8s_object()
        k8s_object.user_id = user_id_from_api_object(obj.obj)
        await cache.upsert(k8s_object)

    return handler


def user_id_from_api_object(obj: APIObject) -> str | None:
    """Get the user id from an api object."""
    match obj.kind.lower():
        case "jupyterserver":
            return cast(str, obj.metadata.labels["renku.io/userId"])
        case "amaltheasession":
            return cast(str, obj.metadata.labels["renku.io/safe-username"])
        case _:
            return None
