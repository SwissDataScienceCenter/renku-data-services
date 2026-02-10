"""K8s watcher database and k8s wrappers."""

from __future__ import annotations

from collections.abc import AsyncIterable, Callable
from dataclasses import dataclass, field
from uuid import uuid4

import sqlalchemy
from kubernetes import client
from kubernetes.utils import parse_quantity
from sqlalchemy import Select, bindparam, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from renku_data_services.app_config import logging
from renku_data_services.crc import models
from renku_data_services.errors import errors
from renku_data_services.k8s.client_interfaces import PriorityClassClient, ResourceQuotaClient
from renku_data_services.k8s.constants import ClusterId
from renku_data_services.k8s.models import DeletePropagationPolicy, K8sObject, K8sObjectFilter, K8sObjectMeta
from renku_data_services.k8s.orm import K8sObjectORM

logger = logging.getLogger(__name__)


class K8sDbCache:
    """Caching k8s objects in postgres."""

    def __init__(self, session_maker: Callable[..., AsyncSession]) -> None:
        self.__session_maker = session_maker

    @staticmethod
    def __get_where_clauses(_filter: K8sObjectFilter) -> Select[tuple[K8sObjectORM]]:
        stmt = select(K8sObjectORM)
        if _filter.name is not None:
            stmt = stmt.where(K8sObjectORM.name == _filter.name)
        if _filter.namespace is not None:
            stmt = stmt.where(K8sObjectORM.namespace == _filter.namespace)
        if _filter.cluster is not None:
            stmt = stmt.where(K8sObjectORM.cluster == str(_filter.cluster))
        if _filter.gvk is not None:
            stmt = stmt.where(K8sObjectORM.kind_insensitive == _filter.gvk.kind)
            stmt = stmt.where(K8sObjectORM.version_insensitive == _filter.gvk.version)
            if _filter.gvk.group is None:
                stmt = stmt.where(K8sObjectORM.group.is_(None))
            else:
                stmt = stmt.where(K8sObjectORM.group_insensitive == _filter.gvk.group)
        if _filter.user_id is not None:
            stmt = stmt.where(K8sObjectORM.user_id == _filter.user_id)
        if _filter.label_selector is not None:
            stmt = stmt.where(
                # K8sObjectORM.manifest.comparator.contains({"metadata": {"labels": filter.label_selector}})
                sqlalchemy.text("manifest -> 'metadata' -> 'labels' @> :labels").bindparams(
                    bindparam("labels", _filter.label_selector, type_=JSONB)
                )
            )
        return stmt

    async def __get(self, meta: K8sObjectMeta, session: AsyncSession) -> K8sObjectORM | None:
        stmt = self.__get_where_clauses(meta.to_filter())
        obj_orm = await session.scalar(stmt)
        return obj_orm

    async def upsert(self, obj: K8sObject) -> None:
        """Insert or update an object in the cache."""
        if obj.user_id is None:
            raise errors.ValidationError(message="user_id is required to upsert k8s object.")
        async with self.__session_maker() as session, session.begin():
            obj_orm = await self.__get(obj, session)
            if obj_orm is not None:
                obj_orm.manifest = obj.manifest
                await session.commit()
                await session.flush()
                return
            obj_orm = K8sObjectORM(
                name=obj.name,
                namespace=obj.namespace or "default",
                group=obj.gvk.group,
                kind=obj.gvk.kind,
                version=obj.gvk.version,
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
            if obj_orm is not None:
                await session.delete(obj_orm)

    async def get(self, meta: K8sObjectMeta) -> K8sObject | None:
        """Get a single object from the cache."""
        async with self.__session_maker() as session, session.begin():
            obj_orm = await self.__get(meta, session)
            if obj_orm is not None:
                return meta.with_manifest(obj_orm.manifest)

        return None

    async def list(self, _filter: K8sObjectFilter) -> AsyncIterable[K8sObject]:
        """List objects from the cache."""
        async with self.__session_maker() as session, session.begin():
            stmt = self.__get_where_clauses(_filter)
            async for res in await session.stream_scalars(stmt):
                yield res.dump()


@dataclass
class QuotaRepository:
    """Adapter for CRUD operations on resource quotas and priority classes in k8s."""

    rq_client: ResourceQuotaClient
    pc_client: PriorityClassClient
    namespace: str = "default"
    _label_name: str = field(init=False, default="app")
    _label_value: str = field(init=False, default="renku")

    def _quota_from_manifest(self, manifest: client.V1ResourceQuota) -> models.Quota:
        gpu = 0
        gpu_kind = models.GpuKind.NVIDIA
        for igpu_kind in models.GpuKind:
            key = f"requests.{igpu_kind}/gpu"
            if key in manifest.spec.hard:
                gpu = int(parse_quantity(manifest.spec.hard.get(key)))
                gpu_kind = igpu_kind
                break
        memory_raw = manifest.spec.hard.get("requests.memory")
        if memory_raw is None:
            raise errors.ValidationError(
                message="Kubernetes resource quota with missing hard.requests.memory is not supported"
            )
        cpu_raw = manifest.spec.hard.get("requests.cpu")
        if cpu_raw is None:
            raise errors.ValidationError(
                message="Kubernetes resource quota with missing hard.requests.cpu is not supported"
            )
        return models.Quota(
            cpu=float(parse_quantity(cpu_raw)),
            memory=round(parse_quantity(memory_raw) / 1_000_000_000),
            gpu=gpu,
            gpu_kind=gpu_kind,
            id=manifest.metadata.name,
        )

    def _quota_to_manifest(self, quota: models.Quota) -> client.V1ResourceQuota:
        return client.V1ResourceQuota(
            metadata=client.V1ObjectMeta(labels={self._label_name: self._label_value}, name=quota.id),
            spec=client.V1ResourceQuotaSpec(
                hard={
                    "requests.cpu": quota.cpu,
                    "requests.memory": str(quota.memory * 1_000_000_000),
                    f"requests.{quota.gpu_kind}/gpu": quota.gpu,
                },
                scope_selector=client.V1ScopeSelector(
                    match_expressions=[{"operator": "In", "scopeName": "PriorityClass", "values": [quota.id]}]
                ),
            ),
        )

    async def get_quota(self, name: str | None, cluster_id: ClusterId) -> models.Quota | None:
        """Get a specific quota by name."""
        if not name:
            return None
        try:
            res_quota = await self.rq_client.read_resource_quota(
                name=name, namespace=self.namespace, cluster_id=cluster_id
            )
        except errors.MissingResourceError:
            return None
        return self._quota_from_manifest(res_quota)

    async def get_quotas(self, cluster_id: ClusterId, name: str | None = None) -> AsyncIterable[models.Quota]:
        """Get a specific resource quota."""
        if name is not None:
            quota = await self.get_quota(name, cluster_id)
            if not quota:
                return
            yield quota
            return
        quotas = self.rq_client.list_resource_quota(
            namespace=self.namespace,
            label_selector={self._label_name: self._label_value},
            cluster_id=cluster_id,
        )
        async for q in quotas:
            yield self._quota_from_manifest(q)

    async def create_quota(self, new_quota: models.UnsavedQuota, cluster_id: ClusterId) -> models.Quota:
        """Create a resource quota and priority class."""
        quota_id = str(uuid4()) if new_quota.id is None else new_quota.id
        quota = models.Quota(
            cpu=new_quota.cpu, memory=new_quota.memory, gpu=new_quota.gpu, gpu_kind=new_quota.gpu_kind, id=quota_id
        )
        metadata = {"labels": {self._label_name: self._label_value}, "name": quota_id}
        quota_manifest = self._quota_to_manifest(quota)

        # Check if we have a priority class with the given name, return it or create one otherwise.
        pc = await self.pc_client.read_priority_class(quota.id, cluster_id)
        logger.warn(f"#### read_priority_class({quota.id,}, {cluster_id}): {pc}")
        if pc is None:
            pc = await self.pc_client.create_priority_class(
                client.V1PriorityClass(
                    global_default=False,
                    value=100,
                    preemption_policy="Never",
                    description="Renku resource quota priority class",
                    metadata=client.V1ObjectMeta(**metadata),
                ),
                cluster_id,
            )

        # NOTE: The priority class is cluster-scoped and a namespace-scoped resource cannot be an owner
        # of a cluster-scoped resource. That is why the priority class is an owner of the quota.
        quota_manifest.owner_references = [
            client.V1OwnerReference(
                api_version=pc.api_version,
                block_owner_deletion=True,
                controller=False,
                kind=pc.kind,
                name=pc.metadata.name,
                uid=pc.metadata.uid,
            )
        ]
        res = await self.rq_client.create_resource_quota(self.namespace, quota_manifest, cluster_id)
        return self._quota_from_manifest(res)

    async def delete_quota(self, name: str, cluster_id: ClusterId) -> None:
        """Delete a resource quota and priority class."""
        await self.pc_client.delete_priority_class(
            name=name, cluster_id=cluster_id, propagation_policy=DeletePropagationPolicy.foreground
        )
        await self.rq_client.delete_resource_quota(name=name, namespace=self.namespace, cluster_id=cluster_id)

    async def update_quota(self, quota: models.Quota, cluster_id: ClusterId) -> models.Quota:
        """Update a specific resource quota."""
        quota_manifest = self._quota_to_manifest(quota)
        patched_quota = await self.rq_client.patch_resource_quota(
            name=quota.id, namespace=self.namespace, body=quota_manifest, cluster_id=cluster_id
        )
        return self._quota_from_manifest(patched_quota)
