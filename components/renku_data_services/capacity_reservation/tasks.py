"""Task definitions."""

import random
from dataclasses import dataclass
from datetime import UTC, datetime

from ulid import ULID

from renku_data_services.app_config import logging
from renku_data_services.capacity_reservation.core import calculate_target_replicas
from renku_data_services.capacity_reservation.db import CapacityReservationRepository, OccurrenceAdapter
from renku_data_services.capacity_reservation.models import (
    CapacityReservation,
    Occurrence,
    OccurrencePatch,
    OccurrenceState,
)
from renku_data_services.k8s.clients import K8sClusterClientsPool
from renku_data_services.k8s.constants import DEFAULT_K8S_CLUSTER
from renku_data_services.k8s.models import GVK, K8sObjectFilter, K8sObjectMeta
from renku_data_services.notebooks.constants import AMALTHEA_SESSION_GVK

DEPLOYMENT_GVK = GVK(kind="Deployment", group="apps", version="v1")


@dataclass(kw_only=True)
class CapacityReservationTasks:
    """Task definitions for capacity reservations."""

    occurrence_adapter: OccurrenceAdapter
    capacity_reservation_repo: CapacityReservationRepository
    k8s_client: K8sClusterClientsPool

    async def activate_pending_occurrences_task(self) -> None:
        """Activate pending capacity reservation occurrences."""
        logger = logging.getLogger(self.__class__.__name__)

        due_pending_occurrences = await self.occurrence_adapter.get_occurrences_due_for_activation()

        if not due_pending_occurrences:
            logger.debug("No pending capacity reservation occurrences are due for activation.")
            return None

        logger.info(f"Activating {len(due_pending_occurrences)} pending capacity reservation occurrence(s).")

        cluster = await self.k8s_client.cluster_by_id(DEFAULT_K8S_CLUSTER)
        namespace = cluster.namespace

        for occurrence in due_pending_occurrences:
            reservations = await self.capacity_reservation_repo.get_capacity_reservations_by_ids(
                [occurrence.reservation_id]
            )
            if not reservations:
                logger.error(
                    f"Could not find capacity reservation with id {occurrence.reservation_id} "
                    f"for occurrence {occurrence.id}."
                )
                continue
            reservation = reservations[0]

            deployment_name = f"capacity-reservation-{str(occurrence.id).lower()}"
            manifest = _build_placeholder_deployment_manifest(occurrence, reservation)
            meta = K8sObjectMeta(
                name=deployment_name, namespace=namespace, cluster=DEFAULT_K8S_CLUSTER, gvk=DEPLOYMENT_GVK
            )

            await self.k8s_client.create(meta.with_manifest(manifest), refresh=False)
            await self.occurrence_adapter.update_occurrence(
                occurrence.id,
                OccurrencePatch(status=OccurrenceState.ACTIVE, deployment_name=deployment_name),
            )

    async def monitor_active_occurrences_task(self) -> None:
        """Monitor active capacity reservation occurrences, scaling up/down or deactivating as needed."""
        logger = logging.getLogger(self.__class__.__name__)

        active_occurrences = await self.occurrence_adapter.get_occurrences_by_properties(status=OccurrenceState.ACTIVE)

        if not active_occurrences:
            logger.debug("No active capacity reservation occurrences to monitor.")
            return None

        logger.info(f"Monitoring {len(active_occurrences)} active capacity reservation occurrence(s).")

        datetime_now = datetime.now(UTC)
        cluster = await self.k8s_client.cluster_by_id(DEFAULT_K8S_CLUSTER)
        namespace = cluster.namespace

        expired_occurrences = [o for o in active_occurrences if o.end_datetime < datetime_now]
        still_active_occurrences = [o for o in active_occurrences if o.end_datetime >= datetime_now]

        for expired_occurrence in expired_occurrences:
            logger.info(f"Deactivating occurrence {expired_occurrence.id} as its end time has passed.")
            if expired_occurrence.deployment_name is None:
                logger.warning(f"Expired occurrence {expired_occurrence.id} has no deployment name, skipping delete.")
            else:
                await self.k8s_client.delete(
                    K8sObjectMeta(
                        name=expired_occurrence.deployment_name,
                        namespace=namespace,
                        cluster=DEFAULT_K8S_CLUSTER,
                        gvk=DEPLOYMENT_GVK,
                    )
                )
            await self.occurrence_adapter.update_occurrence(
                expired_occurrence.id, OccurrencePatch(status=OccurrenceState.COMPLETED)
            )

        if not still_active_occurrences:
            logger.debug("No active capacity reservation occurrences to scale.")
            return None

        session_data = []
        async for s in self.k8s_client.list(
            K8sObjectFilter(
                namespace=namespace,
                cluster=DEFAULT_K8S_CLUSTER,
                gvk=AMALTHEA_SESSION_GVK,
            )
        ):
            session_data.append(
                {
                    "project_id": s.manifest["metadata"]["annotations"].get("renku.io/project_id"),
                    "priority_class_name": s.manifest["spec"]["priorityClassName"],
                    "cpu_request": s.manifest["spec"]["session"]["resources"]["requests"]["cpu"],
                    "memory_request": s.manifest["spec"]["session"]["resources"]["requests"]["memory"],
                    "creation_time": s.manifest["metadata"]["creationTimestamp"],
                }
            )

        active_pairs: list[tuple[Occurrence, CapacityReservation]] = []
        for occurrence in still_active_occurrences:
            reservations = await self.capacity_reservation_repo.get_capacity_reservations_by_ids(
                [occurrence.reservation_id]
            )
            if not reservations:
                logger.error(
                    f"Could not find capacity reservation with id {occurrence.reservation_id} "
                    f"for occurrence {occurrence.id}."
                )
                continue
            reservation = reservations[0]
            active_pairs.append((occurrence, reservation))

        project_template_map: dict[ULID, ULID | None] = {}
        if any(r.matching.project_template_id for _, r in active_pairs):
            project_ids = [ULID.from_str(s["project_id"]) for s in session_data if s.get("project_id") is not None]
            project_template_map = await self.occurrence_adapter.get_project_template_ids(project_ids)

        session_counts = _assign_sessions_to_occurrences(session_data, active_pairs, project_template_map)

        for occurrence, reservation in active_pairs:
            count = session_counts.get(occurrence.id, 0)
            target_replicas = calculate_target_replicas(reservation, occurrence, count, datetime_now)

            if occurrence.deployment_name is None:
                logger.warning(f"Active occurrence {occurrence.id} has no deployment name, skipping patch.")
                continue
            meta = K8sObjectMeta(
                name=occurrence.deployment_name,
                namespace=namespace,
                cluster=DEFAULT_K8S_CLUSTER,
                gvk=DEPLOYMENT_GVK,
            )
            await self.k8s_client.patch(
                meta,
                {"spec": {"replicas": target_replicas}},
            )


    async def cleanup_orphaned_deployments_task(self) -> None:
        """Delete capacity reservation deployments whose occurrences no longer exist in the database."""
        logger = logging.getLogger(self.__class__.__name__)

        cluster = await self.k8s_client.cluster_by_id(DEFAULT_K8S_CLUSTER)
        namespace = cluster.namespace

        deployments = []
        async for d in self.k8s_client.list(
            K8sObjectFilter(
                namespace=namespace,
                cluster=DEFAULT_K8S_CLUSTER,
                gvk=DEPLOYMENT_GVK,
                label_selector={"app": "capacity-placeholder"},
            )
        ):
            deployments.append(d)

        if not deployments:
            return None

        occurrence_ids_from_k8s: dict[ULID, str] = {}
        for d in deployments:
            occurrence_id_str = d.manifest.get("metadata", {}).get("labels", {}).get("renku.io/occurrence-id")
            if occurrence_id_str is None:
                continue
            occurrence_ids_from_k8s[ULID.from_str(occurrence_id_str)] = d.name

        if not occurrence_ids_from_k8s:
            return None

        existing_ids = await self.occurrence_adapter.get_existing_occurrence_ids(list(occurrence_ids_from_k8s.keys()))
        orphaned_ids = set(occurrence_ids_from_k8s.keys()) - existing_ids

        for orphaned_id in orphaned_ids:
            deployment_name = occurrence_ids_from_k8s[orphaned_id]
            logger.info(f"Deleting orphaned deployment {deployment_name} (occurrence {orphaned_id} no longer exists).")
            await self.k8s_client.delete(
                K8sObjectMeta(
                    name=deployment_name,
                    namespace=namespace,
                    cluster=DEFAULT_K8S_CLUSTER,
                    gvk=DEPLOYMENT_GVK,
                )
            )


def _assign_sessions_to_occurrences(
    session_data: list[dict],
    active_pairs: list[tuple[Occurrence, CapacityReservation]],
    project_template_map: dict[ULID, ULID | None],
) -> dict[ULID, int]:
    """Assign sessions to occurrences based on matching criteria and return a count of sessions per occurrence."""

    counts = {occurrence.id: 0 for occurrence, _ in active_pairs}
    unmatched_sessions = session_data.copy()

    for session in session_data:
        if session.get("project_id"):
            project_id = ULID.from_str(session["project_id"])
            project_template_id = project_template_map.get(project_id)

            if project_template_id:
                candidates = [(o, r) for o, r in active_pairs if r.matching.project_template_id == project_template_id]
                if len(candidates) == 1:
                    counts[candidates[0][0].id] += 1
                    unmatched_sessions.remove(session)

    for session in unmatched_sessions.copy():
        if session.get("priority_class_name"):
            candidates = [
                (o, r) for o, r in active_pairs if r.provisioning.priority_class_name == session["priority_class_name"]
            ]
            if len(candidates) == 1:
                counts[candidates[0][0].id] += 1
                unmatched_sessions.remove(session)

    for session in unmatched_sessions.copy():
        if session.get("cpu_request") and session.get("memory_request"):
            candidates = []
            for o, r in active_pairs:
                if (
                    r.provisioning.cpu_request == session["cpu_request"]
                    and r.provisioning.memory_request == session["memory_request"]
                    and (datetime.fromisoformat(session["creation_time"]) >= o.start_datetime)
                ):
                    candidates.append((o, r))

            if len(candidates) == 1:
                counts[candidates[0][0].id] += 1
                unmatched_sessions.remove(session)
            elif len(candidates) > 1:
                logger = logging.getLogger(__name__)
                logger.warning(
                    f"Session with project_id {session.get('project_id')} and "
                    f"priority_class_name {session.get('priority_class_name')} "
                    "matches multiple occurrences. Picking occurrence at random."
                )
                random_choice = random.choice(candidates)  # nosec B311
                counts[random_choice[0].id] += 1
                unmatched_sessions.remove(session)

    return counts


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
