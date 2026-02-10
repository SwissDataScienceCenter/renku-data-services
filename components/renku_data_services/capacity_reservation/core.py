"""Business logic for capacity reservation."""

import logging
from datetime import date, datetime, timedelta
from datetime import UTC

from ulid import ULID

from renku_data_services.capacity_reservation import apispec, models
from renku_data_services.errors import errors

logger = logging.getLogger(__name__)


def validate_schedule_entry(schedule_entry: apispec.ScheduleEntry) -> models.ScheduleEntry:
    """Validate a schedule entry."""
    if schedule_entry.start_time >= schedule_entry.end_time:
        raise errors.ValidationError(message="Schedule entry start time must be before end time")

    return models.ScheduleEntry(
        day_of_week=schedule_entry.day_of_week,
        start_time=schedule_entry.start_time,
        end_time=schedule_entry.end_time,
    )


def validate_recurrence_config(recurrence: apispec.RecurrenceConfig) -> models.RecurrenceConfig:
    """Validate a recurrence configuration."""
    if recurrence.type is None:
        raise errors.ValidationError(message="Recurrence type is required")

    if recurrence.end_date and recurrence.start_date >= recurrence.end_date:
        raise errors.ValidationError(message="Recurrence end date must be after start date")

    if recurrence.type == apispec.RecurrenceType.weekly and not recurrence.schedule:
        raise errors.ValidationError(message="Recurrence schedule is required for weekly recurrence type")

    schedule_entries = [validate_schedule_entry(entry) for entry in recurrence.schedule or []]

    return models.RecurrenceConfig(
        type=models.RecurrenceType(recurrence.type.value),
        start_date=recurrence.start_date,
        end_date=recurrence.end_date,
        schedule=schedule_entries,
    )


def validate_provisioning_config(provisioning: apispec.ProvisioningConfig) -> models.ProvisioningConfig:
    """Validate a provisioning configuration."""

    return models.ProvisioningConfig(
        placeholder_count=provisioning.placeholder_count,
        cpu_request=provisioning.cpu_request,
        memory_request=provisioning.memory_request,
        priority_class_name=provisioning.priority_class_name,
        lead_time_minutes=provisioning.lead_time_minutes,
        scale_down_behavior=models.ScaleDownBehavior(provisioning.scale_down_behavior.value),
    )


def validate_matching_config(matching: apispec.MatchingConfig) -> models.MatchingConfig:
    """Validate a matching configuration."""
    project_template_id = ULID.from_str(matching.project_template_id) if matching.project_template_id else None

    return models.MatchingConfig(
        project_template_id=project_template_id,
        resource_class_id=matching.resource_class_id,
    )


def validate_capacity_reservation(
    capacity_reservation: apispec.CapacityReservationPost,
) -> models.UnsavedCapacityReservation:
    """Validate a capacity reservation."""
    return models.UnsavedCapacityReservation(
        name=capacity_reservation.name,
        recurrence=validate_recurrence_config(capacity_reservation.recurrence),
        provisioning=validate_provisioning_config(capacity_reservation.provisioning),
        matching=validate_matching_config(capacity_reservation.matching),
    )


def _generate_once_occurrences(
    reservation: models.CapacityReservation,
    start: date,
    end: date,
) -> list[models.UnsavedOccurrence]:
    """Generate occurrences for a one-time reservation."""
    if reservation.recurrence.start_date < start or reservation.recurrence.start_date > end:
        return []

    occurrences = []
    for schedule_entry in reservation.recurrence.schedule:
        occurrence = models.UnsavedOccurrence(
            reservation_id=reservation.id,
            start_datetime=datetime.combine(reservation.recurrence.start_date, schedule_entry.start_time, tzinfo=UTC),
            end_datetime=datetime.combine(reservation.recurrence.start_date, schedule_entry.end_time, tzinfo=UTC),
            status=models.OccurrenceState.PENDING,
        )
        occurrences.append(occurrence)

    return occurrences


def _generate_daily_occurrences(
    reservation: models.CapacityReservation,
    start: date,
    end: date,
) -> list[models.UnsavedOccurrence]:
    """Generate occurrences for a daily reservation."""
    occurrences = []
    current_date = start

    while current_date <= end:
        for schedule_entry in reservation.recurrence.schedule:
            occurrence = models.UnsavedOccurrence(
                reservation_id=reservation.id,
                start_datetime=datetime.combine(current_date, schedule_entry.start_time, tzinfo=UTC),
                end_datetime=datetime.combine(current_date, schedule_entry.end_time, tzinfo=UTC),
                status=models.OccurrenceState.PENDING,
            )
            occurrences.append(occurrence)

        current_date += timedelta(days=1)

    return occurrences


def _generate_weekly_occurrences(
    reservation: models.CapacityReservation,
    start: date,
    end: date,
) -> list[models.UnsavedOccurrence]:
    """Generate occurrences for a weekly reservation."""
    occurrences = []
    current_date = start

    while current_date <= end:
        python_weekday = current_date.isoweekday()

        for schedule_entry in reservation.recurrence.schedule:
            if schedule_entry.day_of_week == python_weekday:
                occurrence = models.UnsavedOccurrence(
                    reservation_id=reservation.id,
                    start_datetime=datetime.combine(current_date, schedule_entry.start_time, tzinfo=UTC),
                    end_datetime=datetime.combine(current_date, schedule_entry.end_time, tzinfo=UTC),
                    status=models.OccurrenceState.PENDING,
                )
                occurrences.append(occurrence)

        current_date += timedelta(days=1)

    return occurrences


def generate_occurrences(
    reservation: models.CapacityReservation,
    from_date: date,
    to_date: date,
) -> list[models.UnsavedOccurrence]:
    """Generate occurrences for a reservation within a date range."""
    recurrence = reservation.recurrence
    occurrences: list[models.UnsavedOccurrence] = []

    # Determine the effective date range
    start = max(from_date, recurrence.start_date)
    end = min(to_date, recurrence.end_date) if recurrence.end_date else to_date

    if start > end:
        return []

    match recurrence.type:
        case models.RecurrenceType.ONCE:
            occurrences = _generate_once_occurrences(reservation, start, end)
        case models.RecurrenceType.DAILY:
            occurrences = _generate_daily_occurrences(reservation, start, end)
        case models.RecurrenceType.WEEKLY:
            occurrences = _generate_weekly_occurrences(reservation, start, end)

    return occurrences


def calculate_target_replicas(
    reservation: models.CapacityReservation,
    occurrence: models.Occurrence,
    active_sessions: int,
    now: datetime,
) -> int:
    """Calculate the target number of placeholder replicas for an occurrence."""
    provisioning = reservation.provisioning

    lead_time_delta = timedelta(minutes=provisioning.lead_time_minutes)
    lead_time_start = occurrence.start_datetime - lead_time_delta

    if now < lead_time_start:
        return 0

    if now > occurrence.end_datetime:
        return 0

    if provisioning.scale_down_behavior == models.ScaleDownBehavior.MAINTAIN:
        return provisioning.placeholder_count
    else:
        return max(provisioning.placeholder_count - active_sessions, 0)
