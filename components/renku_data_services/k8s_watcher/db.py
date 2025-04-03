"""K8s watcher database and k8s wrappers."""

from __future__ import annotations

import asyncio
import contextlib
import json
from asyncio import Task
from collections.abc import AsyncIterable, Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Self, cast

import kr8s
import sqlalchemy
from kr8s.asyncio import Api
from kr8s.asyncio.objects import APIObject
from sanic.log import logger
from sqlalchemy import select
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
    def user_id(self) -> str:
        """Extract the user id from annotations."""
        user_id = self.obj.metadata.labels["renku.io/safe-username"]
        if user_id is None:
            raise errors.ValidationError(message="Couldn't find user id on k8s object")
        return cast(str, user_id)

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
            manifest=self.obj.to_dict(),
            cluster=self.cluster,
            user_id=self.user_id,
        )

    @classmethod
    def from_k8s_object(cls, obj: K8sObject, api: Api | None = None) -> Self:
        """Convert a regular k8s object to an api object."""
        return cls(
            obj=APIObject(
                resource=obj.manifest,
                namespace=obj.namespace,
                api=api,
            ),
            cluster=obj.cluster,
        )


type EventHandler = Callable[[APIObjectInCluster], Awaitable[None]]


class K8sClient:
    """A wrapper around a kr8s k8s client, acts on all resource over many clusters."""

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

    async def patch(self, meta: K8sObjectMeta, patch: dict[str, Any]) -> K8sObject:
        """Patch a k8s object."""
        obj = await self.__get(meta)
        if not obj:
            raise errors.MissingResourceError(message=f"The k8s resource with metadata {meta} cannot be found.")
        await obj.obj.patch(patch)
        return meta.with_manifest(obj.obj.to_dict())

    async def delete(self, meta: K8sObjectMeta) -> None:
        """Delete a k8s object."""
        obj = await self.__get(meta)
        if not obj:
            return None
        with contextlib.suppress(kr8s.NotFoundError):
            await obj.obj.delete(propagation_policy="Foreground")

    async def __get(self, meta: K8sObjectMeta) -> APIObjectInCluster | None:
        return await anext(aiter(self.__list(meta.to_list_filter())), None)

    async def get(self, meta: K8sObjectMeta) -> K8sObject | None:
        """Get a specific k8s object, None is returned if the object does not exist."""
        obj = await self.__get(meta)
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
                    api=cluster.api,
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
        obj_orm = await session.scalar(
            select(K8sObjectORM)
            .where(K8sObjectORM.name == meta.name)
            .where(K8sObjectORM.namespace == meta.namespace)
            .where(K8sObjectORM.cluster == meta.cluster)
            .where(K8sObjectORM.kind == meta.kind)
            .where(K8sObjectORM.version == meta.version)
        )
        return obj_orm

    async def upsert(self, obj: K8sObject) -> None:
        """Insert or update an object in the cache."""
        async with self.__session_maker() as session, session.begin():
            obj_orm = await self.__get(obj.meta, session)
            if obj_orm is not None:
                obj_orm.manifest = obj.manifest
                return
            obj_orm = K8sObjectORM(
                name=obj.name,
                namespace=obj.namespace or "default",
                kind=obj.kind,
                version=obj.version,
                manifest=obj.manifest,
                cluster=obj.cluster,
                user_id=obj.user_id,
            )
            session.add(obj_orm)
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
                stmt = stmt.where(K8sObjectORM.kind == filter.kind)
            if filter.version:
                stmt = stmt.where(K8sObjectORM.version == filter.version)
            if filter.label_selector:
                stmt = stmt.where(
                    sqlalchemy.text("manifest -> 'metadata' -> 'labels' @> :labels").bindparams(
                        labels=json.dumps(filter.label_selector)
                    )
                )
            async for res in await session.stream_scalars(stmt):
                yield res.dump()


class CachedK8sClient(K8sClient):
    """A wrapper around a kr8s k8s client.

    Provides access to a cache for listing and reading resources but fallback to the cluster for other operations.
    """

    def __init__(self, clusters: dict[ClusterId, Cluster], cache: K8sDbCache) -> None:
        super().__init__(clusters)
        self.__cache = cache

    async def create(self, obj: K8sObject) -> K8sObject:
        """Create the k8s object."""
        obj = await super().create(obj)
        await self.__cache.upsert(obj)
        return obj

    async def patch(self, meta: K8sObjectMeta, patch: dict[str, Any]) -> K8sObject:
        """Patch a k8s object."""
        obj = await super().patch(meta, patch)
        await self.__cache.upsert(obj)
        return obj

    async def delete(self, meta: K8sObjectMeta) -> None:
        """Delete a k8s object."""
        await super().delete(meta)
        await self.__cache.delete(meta)

    async def get(self, meta: K8sObjectMeta) -> K8sObject | None:
        """Get a specific k8s object, None is returned if the object does not exist."""
        res = await self.__cache.get(meta)
        if res is None:
            return None
        return res

    async def list(self, filter: ListFilter) -> AsyncIterable[K8sObject]:
        """List all k8s objects."""
        results = self.__cache.list(filter)
        async for res in results:
            yield res


class K8sWatcher:
    """Watch k8s events and call the handler with every event."""

    def __init__(self, handler: EventHandler, clusters: dict[ClusterId, Cluster], kind: str) -> None:
        self.__handler = handler
        self.__tasks: dict[ClusterId, Task] | None = None
        self.__kind = kind
        self.__clusters = clusters

    async def __run_single(self, cluster: Cluster) -> None:
        # The loops and error handling here will need some testing and love
        while True:
            try:
                watch = cluster.api.async_watch(kind=self.__kind, namespace=cluster.namespace)
                async for _, obj in watch:
                    await self.__handler(APIObjectInCluster(obj, cluster.id))
            except Exception:  # nosec: B110
                pass

    def start(self) -> None:
        """Start the watcher."""
        if self.__tasks is None:
            self.__tasks = {}
        for cluster in self.__clusters.values():
            self.__tasks[cluster.id] = asyncio.create_task(self.__run_single(cluster))

    async def stop(self, timeout: timedelta = timedelta(seconds=10)) -> None:
        """Stop the watcher or timeout."""
        if self.__tasks is None:
            return
        for task in self.__tasks.values():
            if task.done():
                continue
            task.cancel()
            try:
                async with asyncio.timeout(timeout.total_seconds()):
                    await task
            except TimeoutError:
                logger.error("timeout trying to cancel k8s watche task")
                continue


def k8s_object_handler(cache: K8sDbCache) -> EventHandler:
    """Listens and to k8s events and updates the cache."""

    async def handler(obj: APIObjectInCluster) -> None:
        if obj.obj.metadata.get("deletionTimestamp"):
            # The object is being deleted
            await cache.delete(obj.meta)
            return
        await cache.upsert(obj.to_k8s_object())

    return handler
