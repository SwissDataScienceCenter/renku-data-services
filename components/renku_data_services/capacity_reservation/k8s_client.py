"""K8s client wrapper for capacity reservations."""

from __future__ import annotations

import os
import re
from collections.abc import AsyncGenerator
from io import StringIO
from typing import Any

import yaml

from renku_data_services import errors
from renku_data_services.base_models.core import InternalServiceAdmin, ServiceAdminId
from renku_data_services.capacity_reservation.models import CapacityReservation, Occurrence
from renku_data_services.crc.db import ClusterRepository
from renku_data_services.crc.models import ResourceClass
from renku_data_services.k8s.clients import K8sClusterClientsPool
from renku_data_services.k8s.constants import DEFAULT_K8S_CLUSTER, ClusterId
from renku_data_services.k8s.models import GVK, ClusterConnection, K8sObject, K8sObjectFilter, K8sObjectMeta
from renku_data_services.notebooks.constants import AMALTHEA_SESSION_GVK

_internal_admin = InternalServiceAdmin(id=ServiceAdminId.capacity_reservation)

DEPLOYMENT_GVK = GVK(kind="Deployment", group="apps", version="v1")


def _generate_deployment_name(occurrence: Occurrence, reservation: CapacityReservation) -> str:
    """Generate a sanitized deployment name for a capacity reservation occurrence."""

    safe_name = reservation.name.lower()
    safe_name = safe_name.replace(" ", "-").replace("_", "-")
    safe_name = re.sub(r"[^a-z0-9-]", "", safe_name)
    safe_name = safe_name.strip("-")

    if not safe_name:
        safe_name = "reservation"

    safe_name = safe_name[:26]

    short_id = str(occurrence.id)[:8].lower()

    return f"cr-{safe_name}-{short_id}-{reservation.resource_class_id}"


class CapacityReservationK8sClient:
    """K8s client for capacity reservation operations."""

    def __init__(self, client: K8sClusterClientsPool, cluster_repo: ClusterRepository) -> None:
        self.__client = client
        self.__cluster_repo = cluster_repo
        self.__default_tolerations: list[dict[str, str]] = yaml.safe_load(
            StringIO(os.environ.get("NB_SESSIONS__TOLERATIONS", "[]"))
        )
        self.__default_node_selector: dict[str, str] = yaml.safe_load(
            StringIO(os.environ.get("NB_SESSIONS__NODE_SELECTOR", "{}"))
        )
        self.__default_affinity: dict[str, Any] = yaml.safe_load(
            StringIO(os.environ.get("NB_SESSIONS__AFFINITY", "{}"))
        )
        self.__placeholder_priority_class: str | None = (
            os.environ.get("NB_SESSIONS__PLACEHOLDER_PRIORITY_CLASS") or None
        )

    async def _cluster_for_reservation(self, reservation: CapacityReservation) -> ClusterConnection:
        """Resolve the cluster for a reservation, falling back to the default cluster."""
        cluster_id: ClusterId = DEFAULT_K8S_CLUSTER
        class_id = reservation.resource_class_id
        resolved = await self.__cluster_repo.get_cluster_id_for_resource_class(class_id)
        if resolved is not None:
            cluster_id = resolved
        return await self.__client.cluster_by_id(cluster_id)

    async def create_placeholder_deployment(self, occurrence: Occurrence, reservation: CapacityReservation) -> str:
        """Create a placeholder deployment for the given occurrence. Returns the deployment name."""
        cluster = await self._cluster_for_reservation(reservation)
        resource_class = await self.__cluster_repo.get_resource_class_by_id(
            _internal_admin, reservation.resource_class_id
        )
        if resource_class is None:
            raise errors.MissingResourceError(
                message=f"Resource class {reservation.resource_class_id} not found for occurrence {occurrence.id}."
            )
        deployment_name = _generate_deployment_name(occurrence, reservation)
        manifest = _build_placeholder_deployment_manifest(
            occurrence,
            reservation,
            resource_class,
            self.__default_tolerations,
            self.__default_node_selector,
            self.__default_affinity,
            self.__placeholder_priority_class,
        )
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
            annotations = s.manifest["metadata"]["annotations"]
            resource_class_id_str = annotations.get("renku.io/resource_class_id")
            if resource_class_id_str is None:
                continue
            yield {
                "resource_class_id": int(resource_class_id_str),
                "project_id": annotations.get("renku.io/project_id"),
            }


def _build_placeholder_deployment_manifest(
    occurrence: Occurrence,
    reservation: CapacityReservation,
    resource_class: ResourceClass,
    default_tolerations: list[dict[str, str]],
    default_node_selector: dict[str, str],
    default_affinity: dict[str, Any],
    placeholder_priority_class: str | None,
) -> dict:
    """Build a placeholder deployment manifest for the given occurrence and reservation."""
    labels = {
        "app": "capacity-placeholder",
        "renku.io/capacity-reservation-id": str(reservation.id),
        "renku.io/occurrence-id": str(occurrence.id),
        "renku.io/resource_class_id": str(reservation.resource_class_id),
    }

    cpu_str = f"{round(resource_class.cpu * 1000)}m"
    memory_str = f"{resource_class.memory}Gi"
    requests: dict[str, str | int] = {"cpu": cpu_str, "memory": memory_str}
    limits: dict[str, str | int] = {"memory": memory_str}

    # TODO: Add support for AMD GPUs
    if resource_class.gpu > 0:
        gpu_resource = "nvidia.com/gpu"
        requests[gpu_resource] = resource_class.gpu
        limits[gpu_resource] = resource_class.gpu

    pod_spec: dict = {
        "containers": [
            {
                "name": "placeholder",
                "image": "registry.k8s.io/pause:3.9",
                "resources": {
                    "requests": requests,
                    "limits": limits,
                },
            }
        ],
    }

    if placeholder_priority_class:
        pod_spec["priorityClassName"] = placeholder_priority_class

    if default_node_selector:
        pod_spec["nodeSelector"] = default_node_selector

    tolerations: list[dict[str, str]] = []
    tolerations.extend(default_tolerations)
    for tol_key in resource_class.tolerations:
        tolerations.append({"key": tol_key, "operator": "Exists"})
    if tolerations:
        pod_spec["tolerations"] = tolerations

    affinity_spec: dict[str, Any] = {}
    if default_affinity:
        affinity_spec = default_affinity.copy()

    if resource_class.node_affinities or default_affinity.get("nodeAffinity"):
        required_affinities = [a for a in resource_class.node_affinities if a.required_during_scheduling]

        node_affinity_spec: dict[str, Any] = affinity_spec.get("nodeAffinity", {})

        if required_affinities:
            rc_required = {
                "nodeSelectorTerms": [
                    {
                        "matchExpressions": [
                            {"key": affinity.key, "operator": "Exists"} for affinity in required_affinities
                        ]
                    }
                ]
            }
            if "requiredDuringSchedulingIgnoredDuringExecution" in node_affinity_spec:
                existing_terms = node_affinity_spec["requiredDuringSchedulingIgnoredDuringExecution"].get(
                    "nodeSelectorTerms", []
                )
                rc_required["nodeSelectorTerms"].extend(existing_terms)
            node_affinity_spec["requiredDuringSchedulingIgnoredDuringExecution"] = rc_required

        if node_affinity_spec:
            affinity_spec["nodeAffinity"] = node_affinity_spec

    if affinity_spec:
        pod_spec["affinity"] = affinity_spec

    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": _generate_deployment_name(occurrence, reservation), "labels": labels},
        "spec": {
            "replicas": reservation.provisioning.placeholder_count,
            "selector": {"matchLabels": labels},
            "template": {
                "metadata": {"labels": labels},
                "spec": pod_spec,
            },
        },
    }
