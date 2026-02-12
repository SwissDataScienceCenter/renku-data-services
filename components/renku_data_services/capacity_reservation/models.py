"""Models for capacity reservations."""

from dataclasses import dataclass, field
from datetime import date, datetime, time
from enum import StrEnum

from ulid import ULID


class RecurrenceType(StrEnum):
    """The recurrence types for capacity reservations schedules."""

    ONCE = "once"
    DAILY = "daily"
    WEEKLY = "weekly"


class ScaleDownBehavior(StrEnum):
    """The scale down behaviors for capacity reservations."""

    MAINTAIN = "maintain"
    REDUCE = "reduce"


class OccurrenceState(StrEnum):
    """The occurence states for capacity reservations schedules."""

    PENDING = "pending"
    ACTIVE = "active"
    COMPLETED = "completed"


@dataclass(frozen=True, eq=True, kw_only=True)
class ScheduleEntry:
    """A schedule entry for capacity reservations."""

    day_of_week: int
    start_time: time
    end_time: time


@dataclass(frozen=True, eq=True, kw_only=True)
class RecurrenceConfig:
    """A recurrence configuration for capacity reservations."""

    type: RecurrenceType
    start_date: date
    end_date: date
    schedule: list[ScheduleEntry] = field(default_factory=list)


@dataclass(frozen=True, eq=True, kw_only=True)
class ProvisioningConfig:
    """A provisioning configuration for capacity reservations."""

    placeholder_count: int
    cpu_request: str
    memory_request: str
    priority_class_name: str | None = None
    lead_time_minutes: int
    scale_down_behavior: ScaleDownBehavior = ScaleDownBehavior.REDUCE


@dataclass(frozen=True, eq=True, kw_only=True)
class MatchingConfig:
    """A matching configuration for capacity reservations."""

    project_template_id: ULID | None = None
    resource_class_id: int | None = None


@dataclass(frozen=True, eq=True, kw_only=True)
class UnsavedCapacityReservation:
    """A capacity reservation that has not been persisted yet."""

    name: str
    recurrence: RecurrenceConfig
    provisioning: ProvisioningConfig
    matching: MatchingConfig


@dataclass(frozen=True, eq=True, kw_only=True)
class CapacityReservation(UnsavedCapacityReservation):
    """A capacity reservation stored in the database."""

    id: ULID


@dataclass(frozen=True, eq=True, kw_only=True)
class CapacityReservationPatch:
    """A patch for an existing capacity reservation."""

    name: str | None = None
    recurrence: RecurrenceConfig | None = None
    provisioning: ProvisioningConfig | None = None
    matching: MatchingConfig | None = None


@dataclass(frozen=True, eq=True, kw_only=True)
class UnsavedOccurrence:
    """An occurrence that has not been persisted yet."""

    reservation_id: ULID
    activate_at_datetime: datetime
    start_datetime: datetime
    end_datetime: datetime
    status: OccurrenceState = OccurrenceState.PENDING
    deployment_name: str | None = None


@dataclass(frozen=True, eq=True, kw_only=True)
class Occurrence(UnsavedOccurrence):
    """An occurrence stored in the database."""

    id: ULID


@dataclass(frozen=True, eq=True, kw_only=True)
class OccurrencePatch:
    """A patch for an existing occurrence."""

    activate_at_datetime: datetime | None = None
    start_datetime: datetime | None = None
    end_datetime: datetime | None = None
    status: OccurrenceState | None = None
    deployment_name: str | None = None
