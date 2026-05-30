"""K8s client wrapper for Renku apps."""

from collections.abc import AsyncGenerator
from typing import Any

from renku_data_services.crc.db import ClusterRepository
from renku_data_services.crc.models import ResourceClass
from renku_data_services.k8s.clients import K8sClusterClientsPool
from renku_data_services.k8s.constants import DEFAULT_K8S_CLUSTER, DUMMY_RENKU_APP_USER_ID, ClusterId
from renku_data_services.k8s.models import GVK, K8sObjectMeta
from renku_data_services.project.models import Project
from renku_data_services.renku_apps.crs import KnativeService
from renku_data_services.session.models import SessionLauncher

KNATIVE_SERVICE_GVK = GVK(kind="Service", group="serving.knative.dev", version="v1")

_APP_AUTOSCALING_ANNOTATIONS = {
    "autoscaling.knative.dev/min-scale": "0",
    "autoscaling.knative.dev/max-scale": "3",
    "autoscaling.knative.dev/scale-to-zero-pod-retention-period": "2m",
}


def _generate_app_name(project: Project) -> str:
    """Generate a DNS-1035 label name for an app from its project path."""
    namespace = project.namespace.path.serialize().replace("/", "-")
    return f"{project.slug}-{namespace}".lower()[:63]


class RenkuAppsK8sClient:
    """K8s client for Renku apps operations."""

    def __init__(self, client: K8sClusterClientsPool, cluster_repo: ClusterRepository) -> None:
        self.__client = client
        self.__cluster_repo = cluster_repo

    async def create_app_deployment(
        self, session_launcher: SessionLauncher, resource_class: ResourceClass | None, project: Project
    ) -> KnativeService:
        """Create a deployment for the given app and return the created Knative Service."""
        cluster_id: ClusterId = DEFAULT_K8S_CLUSTER
        cluster = await self.__client.cluster_by_id(cluster_id)
        app_name = _generate_app_name(project)
        manifest = _build_app_deployment_manifest(session_launcher, app_name, resource_class)
        meta = K8sObjectMeta(
            name=app_name,
            namespace=cluster.namespace,
            cluster=cluster.id,
            gvk=KNATIVE_SERVICE_GVK,
            user_id=DUMMY_RENKU_APP_USER_ID,
        )
        created = await self.__client.create(
            meta.with_manifest(manifest.model_dump(exclude_none=True, mode="json")), refresh=True
        )
        return KnativeService.model_validate(created.manifest)

    async def get_app_deployment(self, app_name: str) -> KnativeService | None:
        """Get the deployment for the given app name, or None if it does not exist."""
        cluster_id: ClusterId = DEFAULT_K8S_CLUSTER
        cluster = await self.__client.cluster_by_id(cluster_id)
        meta = K8sObjectMeta(
            name=app_name,
            namespace=cluster.namespace,
            cluster=cluster.id,
            gvk=KNATIVE_SERVICE_GVK,
            user_id=DUMMY_RENKU_APP_USER_ID,
        )
        obj = await self.__client.get(meta)
        if obj is None:
            return None
        return KnativeService.model_validate(obj.manifest)

    async def get_app_deployment_for_project(self, project: Project) -> KnativeService | None:
        """Get the app deployment for the given project, or None if it does not exist."""
        return await self.get_app_deployment(_generate_app_name(project))

    async def delete_app_deployment(self, app_name: str) -> None:
        """Delete the deployment for the given app name. NOT IMPLEMENTED."""
        raise NotImplementedError("Deleting app deployment is not implemented yet")

    async def list_app_deployments(self) -> AsyncGenerator[KnativeService, None]:
        """List all app deployments. NOT IMPLEMENTED."""
        raise NotImplementedError("Listing app deployments is not implemented yet")

    async def update_app_deployment(self, app_name: str, session_launcher: SessionLauncher) -> KnativeService:
        """Update the deployment for the given app name. NOT IMPLEMENTED."""
        raise NotImplementedError("Updating app deployment is not implemented yet")


def _resources_from_resource_class(resource_class: ResourceClass) -> dict[str, Any]:
    """Build a k8s container resources block from a resource class."""
    return {
        "requests": {
            "cpu": f"{round(resource_class.cpu * 1000)}m",
            "memory": f"{resource_class.memory}Gi",
        },
        "limits": {"memory": f"{resource_class.memory}Gi"},
    }


def _build_app_deployment_manifest(
    session_launcher: SessionLauncher, app_name: str, resource_class: ResourceClass | None
) -> KnativeService:
    """Build a Knative Service manifest derived from the session launcher."""
    environment = session_launcher.environment

    container: dict[str, Any] = {
        "image": environment.container_image,
        "ports": [{"containerPort": environment.port}],
        "securityContext": {
            "runAsUser": environment.uid,
            "runAsGroup": environment.gid,
        },
    }
    if resource_class is not None:
        container["resources"] = _resources_from_resource_class(resource_class)
    if session_launcher.env_variables:
        container["env"] = [{"name": var.name, "value": var.value} for var in session_launcher.env_variables]
    if environment.command:
        container["command"] = environment.command
    if environment.args:
        container["args"] = environment.args
    if environment.working_directory is not None:
        container["workingDir"] = str(environment.working_directory)

    return KnativeService.model_validate(
        {
            "apiVersion": "serving.knative.dev/v1",
            "kind": "Service",
            "metadata": {
                "name": app_name,
                "annotations": {
                    "renku.io/launcher_id": str(session_launcher.id),
                    "renku.io/project_id": str(session_launcher.project_id),
                },
            },
            "spec": {
                "template": {
                    "metadata": {"annotations": _APP_AUTOSCALING_ANNOTATIONS},
                    "spec": {"containers": [container]},
                },
            },
        }
    )
