"""K8s watcher database and k8s wrappers."""

from __future__ import annotations

from collections.abc import AsyncIterable, Callable
from dataclasses import dataclass, field
from typing import Optional

import sqlalchemy
from kubernetes import client
from kubernetes.utils import parse_quantity
from sqlalchemy import Select, bindparam, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from renku_data_services.crc import models
from renku_data_services.errors import errors
from renku_data_services.k8s.client_interfaces import PriorityClassClient, ResourceQuotaClient
from renku_data_services.k8s.models import K8sObject, K8sObjectFilter, K8sObjectMeta
from renku_data_services.k8s.orm import K8sObjectORM


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
                gpu = int(manifest.spec.hard.get(key))
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
        if quota.id is None:
            raise errors.ValidationError(message="The id of a quota has to be set when it is created.")
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

    def get_quota(self, name: str | None) -> Optional[models.Quota]:
        """Get a specific quota by name."""
        if not name:
            return None
        try:
            res_quota = self.rq_client.read_resource_quota(name=name, namespace=self.namespace)
        except client.ApiException as e:
            if e.status == 404:
                return None
            raise
        return self._quota_from_manifest(res_quota)

    def get_quotas(self, name: Optional[str] = None) -> list[models.Quota]:
        """Get a specific resource quota."""
        if name is not None:
            quota = self.get_quota(name)
            return [quota] if quota is not None else []
        quotas = self.rq_client.list_resource_quota(
            namespace=self.namespace, label_selector=f"{self._label_name}={self._label_value}"
        )
        return [self._quota_from_manifest(q) for q in quotas]

    def create_quota(self, quota: models.Quota) -> models.Quota:
        """Create a resource quota and priority class."""

        metadata = {"labels": {self._label_name: self._label_value}, "name": quota.id}
        quota_manifest = self._quota_to_manifest(quota)

        # Check if we have a priority class with the given name, return it or create one otherwise.
        pc = self.pc_client.read_priority_class(quota.id)
        if pc is None:
            pc = self.pc_client.create_priority_class(
                client.V1PriorityClass(
                    global_default=False,
                    value=100,
                    preemption_policy="Never",
                    description="Renku resource quota priority class",
                    metadata=client.V1ObjectMeta(**metadata),
                ),
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
        self.rq_client.create_resource_quota(self.namespace, quota_manifest)
        return quota

    def delete_quota(self, name: str) -> None:
        """Delete a resource quota and priority class."""
        self.pc_client.delete_priority_class(name=name, body=client.V1DeleteOptions(propagation_policy="Foreground"))
        self.rq_client.delete_resource_quota(name=name, namespace=self.namespace)

    def update_quota(self, quota: models.Quota) -> models.Quota:
        """Update a specific resource quota."""

        quota_manifest = self._quota_to_manifest(quota)
        self.rq_client.patch_resource_quota(name=quota.id, namespace=self.namespace, body=quota_manifest)
        return quota
