"""K8s client wrapper for capacity reservations."""

from __future__ import annotations

from collections.abc import AsyncGenerator

from renku_data_services.capacity_reservation.models import CapacityReservation, Occurrence
from renku_data_services.crc.db import ClusterRepository
from renku_data_services.k8s.clients import K8sClusterClientsPool
from renku_data_services.k8s.constants import DEFAULT_K8S_CLUSTER, ClusterId
from renku_data_services.k8s.models import GVK, ClusterConnection, K8sObject, K8sObjectFilter, K8sObjectMeta
from renku_data_services.notebooks.constants import AMALTHEA_SESSION_GVK

DEPLOYMENT_GVK = GVK(kind="Deployment", group="apps", version="v1")


class CapacityReservationK8sClient:
    """K8s client for capacity reservation operations."""

    def __init__(self, client: K8sClusterClientsPool, cluster_repo: ClusterRepository) -> None:
        self.__client = client
        self.__cluster_repo = cluster_repo

    async def _cluster_for_reservation(self, reservation: CapacityReservation) -> ClusterConnection:
        """Resolve the cluster for a reservation, falling back to the default cluster."""
        cluster_id: ClusterId = DEFAULT_K8S_CLUSTER
        class_id = reservation.matching.resource_class_id
        if class_id is not None:
            resolved = await self.__cluster_repo.get_cluster_id_for_resource_class(class_id)
            if resolved is not None:
                cluster_id = resolved
        return await self.__client.cluster_by_id(cluster_id)

    async def create_placeholder_deployment(self, occurrence: Occurrence, reservation: CapacityReservation) -> str:
        """Create a placeholder deployment for the given occurrence. Returns the deployment name."""
        cluster = await self._cluster_for_reservation(reservation)
        deployment_name = f"capacity-reservation-{str(occurrence.id).lower()}"
        manifest = _build_placeholder_deployment_manifest(occurrence, reservation)
        meta = K8sObjectMeta(
            name=deployment_name,
            namespace=cluster.namespace,
            cluster=cluster.id,
            gvk=DEPLOYMENT_GVK,
        )
        await self.__client.create(meta.with_manifest(manifest), refresh=False)
        return deployment_name

    async def delete_deployment(self, name: str, reservation: CapacityReservation) -> None:
        """Delete a placeholder deployment, resolving the cluster from the reservation."""
        cluster = await self._cluster_for_reservation(reservation)
        await self.__client.delete(
            K8sObjectMeta(
                name=name,
                namespace=cluster.namespace,
                cluster=cluster.id,
                gvk=DEPLOYMENT_GVK,
            )
        )

    async def delete_deployment_object(self, obj: K8sObject) -> None:
        """Delete a placeholder deployment from a K8sObject returned by list_placeholder_deployments."""
        await self.__client.delete(obj)

    async def patch_deployment_replicas(self, name: str, reservation: CapacityReservation, replicas: int) -> None:
        """Scale a placeholder deployment to the given replica count."""
        cluster = await self._cluster_for_reservation(reservation)
        meta = K8sObjectMeta(
            name=name,
            namespace=cluster.namespace,
            cluster=cluster.id,
            gvk=DEPLOYMENT_GVK,
        )
        await self.__client.patch(meta, {"spec": {"replicas": replicas}})

    async def list_placeholder_deployments(self) -> AsyncGenerator[K8sObject, None]:
        """List all capacity-placeholder deployments across all clusters."""
        async for obj in self.__client.list(
            K8sObjectFilter(
                gvk=DEPLOYMENT_GVK,
                label_selector={"app": "capacity-placeholder"},
            )
        ):
            yield obj

    async def list_sessions(self) -> AsyncGenerator[dict, None]:
        """List all AmaltheaSession objects across all clusters, yielding relevant fields as dicts."""
        async for s in self.__client.list(K8sObjectFilter(gvk=AMALTHEA_SESSION_GVK)):
            yield {
                "project_id": s.manifest["metadata"]["annotations"].get("renku.io/project_id"),
                "priority_class_name": s.manifest["spec"]["priorityClassName"],
                "cpu_request": s.manifest["spec"]["session"]["resources"]["requests"]["cpu"],
                "memory_request": s.manifest["spec"]["session"]["resources"]["requests"]["memory"],
                "creation_time": s.manifest["metadata"]["creationTimestamp"],
            }


def _build_placeholder_deployment_manifest(occurrence: Occurrence, reservation: CapacityReservation) -> dict:
    """Build a placeholder deployment manifest for the given occurrence and reservation."""
    labels = {
        "app": "capacity-placeholder",
        "renku.io/reservation-id": str(reservation.id),
        "renku.io/occurrence-id": str(occurrence.id),
    }
    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": f"capacity-reservation-{str(occurrence.id).lower()}", "labels": labels},
        "spec": {
            "replicas": reservation.provisioning.placeholder_count,
            "selector": {"matchLabels": labels},
            "template": {
                "metadata": {"labels": labels},
                "spec": {
                    "priorityClassName": reservation.provisioning.priority_class_name,
                    "containers": [
                        {
                            "name": "placeholder",
                            "image": "registry.k8s.io/pause:3.9",
                            "resources": {
                                "requests": {
                                    "cpu": reservation.provisioning.cpu_request,
                                    "memory": reservation.provisioning.memory_request,
                                }
                            },
                        }
                    ],
                },
            },
        },
    }
