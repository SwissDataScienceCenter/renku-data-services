"""K8s watcher database and k8s wrappers."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterable, Callable

import sqlalchemy
from sqlalchemy import bindparam, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from renku_data_services.errors import errors
from renku_data_services.k8s.models import K8sObject, K8sObjectFilter, K8sObjectMeta
from renku_data_services.k8s_watcher.orm import K8sObjectORM


class K8sDbCache:
    """Caching k8s objects in postgres."""

    def __init__(self, session_maker: Callable[..., AsyncSession]) -> None:
        self.__session_maker = session_maker

    @staticmethod
    async def __get(meta: K8sObjectMeta, session: AsyncSession) -> K8sObjectORM | None:
        stmt = (
            select(K8sObjectORM)
            .where(K8sObjectORM.name == meta.name)
            .where(K8sObjectORM.namespace == meta.namespace)
            .where(K8sObjectORM.cluster == meta.cluster)
            .where(K8sObjectORM.kind == meta.kind)
            .where(K8sObjectORM.version == meta.version)
        )
        if meta.user_id is not None:
            stmt = stmt.where(K8sObjectORM.user_id == meta.user_id)
        logging.warning(f"getting resourceuu{meta}")

        obj_orm = await session.scalar(stmt)
        logging.warning(f"got resource from db: {obj_orm}")
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
                kind=obj.singular,
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

    async def list(self, _filter: K8sObjectFilter) -> AsyncIterable[K8sObject]:
        """List objects from the cache."""
        async with self.__session_maker() as session, session.begin():
            stmt = select(K8sObjectORM)
            if _filter.name:
                stmt = stmt.where(K8sObjectORM.name == _filter.name)
            if _filter.namespace:
                stmt = stmt.where(K8sObjectORM.namespace == _filter.namespace)
            if _filter.cluster:
                stmt = stmt.where(K8sObjectORM.cluster == _filter.cluster)
            if _filter.kind:
                stmt = stmt.where(K8sObjectORM.kind == _filter.kind.lower())
            if _filter.version:
                stmt = stmt.where(K8sObjectORM.version == _filter.version)
            if _filter.user_id:
                stmt = stmt.where(K8sObjectORM.user_id == _filter.user_id)
            if _filter.label_selector:
                stmt = stmt.where(
                    # K8sObjectORM.manifest.comparator.contains({"metadata": {"labels": filter.label_selector}})
                    sqlalchemy.text("manifest -> 'metadata' -> 'labels' @> :labels").bindparams(
                        bindparam("labels", _filter.label_selector, type_=JSONB)
                    )
                )
            async for res in await session.stream_scalars(stmt):
                yield res.dump()
