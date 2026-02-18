"""Task definitions."""

import random
from dataclasses import dataclass
from datetime import UTC, datetime

from ulid import ULID

from renku_data_services.app_config import logging
from renku_data_services.capacity_reservation.core import calculate_target_replicas
from renku_data_services.capacity_reservation.db import CapacityReservationRepository, OccurrenceAdapter
from renku_data_services.capacity_reservation.k8s_client import CapacityReservationK8sClient
from renku_data_services.capacity_reservation.models import (
    CapacityReservation,
    Occurrence,
    OccurrencePatch,
    OccurrenceState,
)
from renku_data_services.k8s.models import K8sObject


@dataclass(kw_only=True)
class CapacityReservationTasks:
    """Task definitions for capacity reservations."""

    occurrence_adapter: OccurrenceAdapter
    capacity_reservation_repo: CapacityReservationRepository
    k8s_client: CapacityReservationK8sClient

    async def activate_pending_occurrences_task(self) -> None:
        """Activate pending capacity reservation occurrences."""
        logger = logging.getLogger(self.__class__.__name__)

        due_pending_occurrences = await self.occurrence_adapter.get_occurrences_due_for_activation()

        if not due_pending_occurrences:
            logger.debug("No pending capacity reservation occurrences are due for activation.")
            return None

        logger.info(f"Activating {len(due_pending_occurrences)} pending capacity reservation occurrence(s).")

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

            deployment_name = await self.k8s_client.create_placeholder_deployment(occurrence, reservation)
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
        expired_occurrences = [o for o in active_occurrences if o.end_datetime < datetime_now]
        still_active_occurrences = [o for o in active_occurrences if o.end_datetime >= datetime_now]

        for expired_occurrence in expired_occurrences:
            logger.info(f"Deactivating occurrence {expired_occurrence.id} as its end time has passed.")
            if expired_occurrence.deployment_name is None:
                logger.warning(f"Expired occurrence {expired_occurrence.id} has no deployment name, skipping delete.")
            else:
                reservations = await self.capacity_reservation_repo.get_capacity_reservations_by_ids(
                    [expired_occurrence.reservation_id]
                )
                if reservations:
                    await self.k8s_client.delete_deployment(expired_occurrence.deployment_name, reservations[0])
                else:
                    logger.error(
                        f"Could not find reservation for expired occurrence {expired_occurrence.id}, skipping delete."
                    )
            await self.occurrence_adapter.update_occurrence(
                expired_occurrence.id, OccurrencePatch(status=OccurrenceState.COMPLETED)
            )

        if not still_active_occurrences:
            logger.debug("No active capacity reservation occurrences to scale.")
            return None

        session_data = []
        async for session in self.k8s_client.list_sessions():
            session_data.append(session)

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
            active_pairs.append((occurrence, reservations[0]))

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
            await self.k8s_client.patch_deployment_replicas(occurrence.deployment_name, reservation, target_replicas)

    async def cleanup_orphaned_deployments_task(self) -> None:
        """Delete capacity reservation deployments whose occurrences no longer exist in the database."""
        logger = logging.getLogger(self.__class__.__name__)

        deployments: list[K8sObject] = []
        occurrence_ids: list[ULID] = []

        async for d in self.k8s_client.list_placeholder_deployments():
            deployments.append(d)
            occurrence_id_str = d.manifest.get("metadata", {}).get("labels", {}).get("renku.io/occurrence-id")
            if occurrence_id_str is not None:
                occurrence_ids.append(ULID.from_str(occurrence_id_str))

        if not occurrence_ids:
            return None

        existing_ids = await self.occurrence_adapter.get_existing_occurrence_ids(occurrence_ids)
        orphaned_ids = set(occurrence_ids) - existing_ids

        for d in deployments:
            occurrence_id_str = d.manifest.get("metadata", {}).get("labels", {}).get("renku.io/occurrence-id")
            if occurrence_id_str is None:
                continue
            occurrence_id = ULID.from_str(occurrence_id_str)
            if occurrence_id in orphaned_ids:
                logger.info(f"Deleting orphaned deployment {d.name} (occurrence {occurrence_id} no longer exists).")
                await self.k8s_client.delete_deployment_object(d)


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
