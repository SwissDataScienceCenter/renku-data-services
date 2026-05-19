"""K8s client wrapper for Renku apps"""

from collections.abc import AsyncGenerator

from renku_data_services.session.models import SessionLauncher
from renku_data_services.crc.db import ClusterRepository
from renku_data_services.k8s.clients import K8sClusterClientsPool
from renku_data_services.k8s.constants import DEFAULT_K8S_CLUSTER, ClusterId
from renku_data_services.k8s.models import GVK, K8sObjectMeta
from renku_data_services.renku_apps.crs import KnativeService

KNATIVE_SERVICE_GVK = GVK(kind="Service", group="serving.knative.dev", version="v1")


def _generate_app_name(session_launcher: SessionLauncher) -> str:
    """Generate a name for an app."""
    return f"app-{session_launcher.id}".lower()[:63]


class RenkuAppsK8sClient:
    """K8s client for Renku apps operations"""

    def __init__(self, client: K8sClusterClientsPool, cluster_repo: ClusterRepository) -> None:
        self.__client = client
        self.__cluster_repo = cluster_repo

    async def create_app_deployment(self, session_launcher: SessionLauncher) -> str:
        """Create a deployment for the given app and return the deployment name"""
        cluster_id: ClusterId = DEFAULT_K8S_CLUSTER
        cluster = await self.__client.cluster_by_id(cluster_id)
        app_name = _generate_app_name(session_launcher)
        manifest = _build_app_deployment_manifest(session_launcher, app_name)
        meta = K8sObjectMeta(name=app_name, namespace=cluster.namespace, cluster=cluster.id, gvk=KNATIVE_SERVICE_GVK)
        await self.__client.create(meta.with_manifest(manifest), refresh=False)
        return app_name

    async def get_app_deployment(self, app_name: str) -> KnativeService | None:
        """Get the deployment for the given app name. NOT IMPLEMENTED"""
        raise NotImplementedError("Getting app deployment is not implemented yet")

    async def delete_app_deployment(self, app_name: str) -> None:
        """Delete the deployment for the given app name. NOT IMPLEMENTED"""
        raise NotImplementedError("Deleting app deployment is not implemented yet")

    async def list_app_deployments(self) -> AsyncGenerator[KnativeService, None]:
        """List all app deployments. NOT IMPLEMENTED"""
        raise NotImplementedError("Listing app deployments is not implemented yet")

    async def update_app_deployment(self, app_name: str, session_launcher: SessionLauncher) -> KnativeService:
        """Update the deployment for the given app name. NOT IMPLEMENTED"""
        raise NotImplementedError("Updating app deployment is not implemented yet")


def _build_app_deployment_manifest(session_launcher: SessionLauncher, app_name: str) -> KnativeService:
    """Build an app deployment manifest for the given app and session launcher"""
    return KnativeService(
        apiVersion="serving.knative.dev/v1",
        kind="Service",
        metadata={"name": app_name},
        spec={
            "template": {
                "spec": {
                    "containers": [
                        {
                            "image": "docker.io/library/nginx:latest",
                            "ports": [{"containerPort": 80}],
                        }
                    ]
                }
            }
        },
    )
