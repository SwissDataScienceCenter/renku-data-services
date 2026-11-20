"""Sync the state of PVCs backing project storage."""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncScalarResult, AsyncSession

from renku_data_services.app_config import logging
from renku_data_services.k8s.clients import K8sClusterClientsPool
from renku_data_services.k8s.constants import DEFAULT_K8S_CLUSTER, ClusterId
from renku_data_services.k8s.models import (
    ClusterConnection,
    K8sObjectMeta,
    K8sPatches,
    K8sPersistentVolumeClaimV2,
)
from renku_data_services.storage import orm as schemas
from renku_data_services.storage.db import ProjectStorageV2Repository

logger = logging.getLogger(__name__)


class ProjectStorageSyncHanlder:
    """Handles syncing the state of PVCs backing project storage with the database."""

    def __init__(
        self,
        k8s_client: ProjectStorageK8sClient,
        project_storage_v2_repo: ProjectStorageV2Repository,
        session_maker: Callable[..., AsyncSession],
    ) -> None:
        self.k8s_client = k8s_client
        self.project_storage_v2_repo = project_storage_v2_repo
        self.session_maker = session_maker

    async def sync_storages(self) -> None:
        """Sync the state of PVCs backing project storage with the database."""
        async with self.session_maker() as session:
            # 1. Get all project storages
            async with session.begin():
                stream = await self._get_all_project_storages_orm(session=session)
                storages_orm = [storage_orm async for storage_orm in stream]
            # 2. Update the status for PVCs with unknown actual size
            for storage_orm in storages_orm:
                logger.info(f"Sync project storage '{str(storage_orm.id)}' with PVC '{storage_orm.k8s_pvc_name}'")
                if storage_orm.k8s_pvc_name is None or storage_orm.actual_size is not None:
                    continue
                async with session.begin():
                    sq_orm = await self.project_storage_v2_repo._get_storage_quota_and_resource_pool_without_authz_or_none_orm(  # noqa E501
                        session=session, storage_quota_id=storage_orm.storage_quota_id
                    )
                    if sq_orm is None:
                        logger.error(
                            f"Storage quota with ID '{storage_orm.storage_quota_id}' does not exist "
                            f"from project storage '{storage_orm.id}'."
                        )
                        continue
                    rp_orm = sq_orm.resource_pool
                    cluster_id = ClusterId(rp_orm.cluster_id) if rp_orm.cluster_id is not None else None
                    cluster = await self.k8s_client.cluster_by_id(cluster_id=cluster_id)
                    namespace = cluster.namespace
                    meta = K8sPersistentVolumeClaimV2.meta(
                        name=storage_orm.k8s_pvc_name, namespace=namespace, cluster_id=cluster.id
                    )
                    pvc = await self.k8s_client.get_persistent_volume_claim_v2(meta)
                    if pvc is None:
                        logger.error(
                            f"Storage quota with ID '{storage_orm.storage_quota_id}' has lost its persistent volume."
                        )
                        continue
                    # Update the storage attributes from k8s
                    async with self.project_storage_v2_repo._with_locked_project_storage(
                        session=session, storage_orm=storage_orm
                    ) as locked_orm:
                        locked_orm.k8s_pvc_status = pvc.get_status()
                        locked_orm.actual_size = pvc.get_actual_size()
                        await session.flush()
                        await session.refresh(locked_orm)

    async def _get_all_project_storages_orm(
        self,
        session: AsyncSession,
    ) -> AsyncScalarResult[schemas.ProjectStorageV2ORM]:
        stmt = select(schemas.ProjectStorageV2ORM).order_by(schemas.ProjectStorageV2ORM.id.asc())
        return await session.stream_scalars(stmt)


class ProjectStorageK8sClient:
    """K8s client for project storage operations."""

    def __init__(self, client: K8sClusterClientsPool) -> None:
        self.__client = client

    async def cluster_by_id(self, cluster_id: ClusterId | None) -> ClusterConnection:
        """Get cluster by ID."""
        cluster_id = cluster_id if cluster_id is not None else DEFAULT_K8S_CLUSTER
        return await self.__client.cluster_by_id(cluster_id)

    # NOTE: fully cluster-aware methods below
    async def get_persistent_volume_claim_v2(self, pvc: K8sObjectMeta) -> K8sPersistentVolumeClaimV2 | None:
        """Get a persistent volume claim (v2)."""
        obj = await self.__client.get(pvc)
        return K8sPersistentVolumeClaimV2.from_k8s_object(obj) if obj is not None else None

    async def create_persistent_volume_claim_v2(self, pvc: K8sPersistentVolumeClaimV2) -> K8sPersistentVolumeClaimV2:
        """Create a persistent volume claim (v2)."""
        obj = await self.__client.create(pvc, True)
        return K8sPersistentVolumeClaimV2.from_k8s_object(obj)

    async def patch_persistent_volume_claim_v2(
        self, pvc: K8sObjectMeta, patch: K8sPatches
    ) -> K8sPersistentVolumeClaimV2:
        """Patch a persistent volume claim (v2)."""
        obj = await self.__client.patch(pvc, patch)
        return K8sPersistentVolumeClaimV2.from_k8s_object(obj)

    async def delete_persistent_volume_claim_v2(self, pvc: K8sObjectMeta) -> None:
        """Delete a persistent volume claim (v2)."""
        await self.__client.delete(pvc)
