"""Module for managing volumes associated to projects."""

from ulid import ULID

from renku_data_services.app_config import logging
from renku_data_services.base_models.bytesize import ByteSize
from renku_data_services.errors import errors
from renku_data_services.k8s.models import ClusterConnection, K8sPersistentVolumeClaim
from renku_data_services.notebooks.api.classes.k8s_client import NotebookK8sClient
from renku_data_services.storage.models import DeletedProjectStorage, ProjectStorage

logger = logging.getLogger(__name__)


class ProjectStorageK8s:
    """Manage persistent volumes associated to a project."""

    def __init__(self, k8s_client: NotebookK8sClient) -> None:
        self.__k8s_client = k8s_client

    def __pvc_name(self, storage: ProjectStorage | DeletedProjectStorage | ULID) -> str:
        if isinstance(storage, ULID):
            return f"pv-{storage}-0".lower()
        else:
            return f"pv-{storage.project_id}-0".lower()

    async def get_volume(self, project_id: ULID) -> K8sPersistentVolumeClaim | None:
        """Get the pvc making the storage of the given project."""

        name = self.__pvc_name(project_id)
        return await self.__k8s_client.get_persistent_volume_claim(name)

    async def get_or_create_volume(
        self, storage: ProjectStorage, cluster: ClusterConnection
    ) -> K8sPersistentVolumeClaim:
        """Either creates a persistent volume or fetches an existing one."""
        name = self.__pvc_name(storage)
        pvc = await self.__k8s_client.get_persistent_volume_claim(name)
        if not pvc:
            logger.debug(f"Create project storage for project: {storage.project_id} with name {name}")
            pvc = K8sPersistentVolumeClaim.new(
                cluster=cluster.id,
                name=name,
                namespace=cluster.namespace,
                accessModes=["ReadWriteMany"],
                storage_class=storage.storage_class,
                size=storage.size,
                labels={"renku.io/project_id": str(storage.project_id)},
            )
            await self.__k8s_client.create_persistent_volume(pvc)
        return pvc

    async def delete_volume(self, project: DeletedProjectStorage | ULID) -> None:
        """Delete a persistent volume associated to the project."""

        name = self.__pvc_name(project)
        await self.__k8s_client.delete_persistent_volume(name)

    async def extend_volume(self, project_id: ULID, new_size: ByteSize) -> K8sPersistentVolumeClaim:
        """Extends the size of an existing volume."""
        existing_pvc = await self.get_volume(project_id)
        new_size_str = f"{new_size.to_gibi()}Gi"
        name = self.__pvc_name(project_id)
        if existing_pvc:
            logger.info(f"Extending pvc {name} to size {new_size_str}")
            await self.__k8s_client.patch_persistent_volume(
                existing_pvc.meta, {"spec": {"resources": {"requests": {"storage": new_size_str}}}}
            )
            existing_pvc.manifest.spec.resources.requests.storage = new_size_str
            return existing_pvc
        else:
            raise errors.MissingResourceError(message=f"PVC {name} not found")
