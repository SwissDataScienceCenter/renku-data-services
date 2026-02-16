"""SQLAlchemy schemas for the capacity reservation database."""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Any, Optional

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, MetaData, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, MappedAsDataclass, mapped_column
from ulid import ULID

from renku_data_services.capacity_reservation import models
from renku_data_services.utils.sqlalchemy import ULIDType

JSONVariant = JSON().with_variant(JSONB(), "postgresql")
metadata_obj = MetaData(schema="capacity_reservation")


class BaseORM(MappedAsDataclass, DeclarativeBase):
    """Base class for all ORM classes."""

    metadata = metadata_obj


def _recurrence_to_dict(recurrence: models.RecurrenceConfig) -> dict[str, Any]:
    """Serialize a RecurrenceConfig to a dict for JSONB storage."""
    return {
        "type": recurrence.type.value,
        "start_date": recurrence.start_date.isoformat(),
        "end_date": recurrence.end_date.isoformat(),
        "schedule": [
            {
                "day_of_week": entry.day_of_week,
                "start_time": entry.start_time.isoformat(),
                "end_time": entry.end_time.isoformat(),
            }
            for entry in recurrence.schedule
        ],
    }


def _recurrence_from_dict(data: dict[str, Any]) -> models.RecurrenceConfig:
    """Deserialize a RecurrenceConfig from a JSONB dict."""
    return models.RecurrenceConfig(
        type=models.RecurrenceType(data["type"]),
        start_date=date.fromisoformat(data["start_date"]),
        end_date=date.fromisoformat(data["end_date"]),
        schedule=[
            models.ScheduleEntry(
                day_of_week=entry["day_of_week"],
                start_time=time.fromisoformat(entry["start_time"]),
                end_time=time.fromisoformat(entry["end_time"]),
            )
            for entry in data.get("schedule", [])
        ],
    )


def _provisioning_to_dict(provisioning: models.ProvisioningConfig) -> dict[str, Any]:
    """Serialize a ProvisioningConfig to a dict for JSONB storage."""
    return {
        "placeholder_count": provisioning.placeholder_count,
        "cpu_request": provisioning.cpu_request,
        "memory_request": provisioning.memory_request,
        "priority_class_name": provisioning.priority_class_name,
        "lead_time_minutes": provisioning.lead_time_minutes,
        "scale_down_behavior": provisioning.scale_down_behavior.value,
    }


def _provisioning_from_dict(data: dict[str, Any]) -> models.ProvisioningConfig:
    """Deserialize a ProvisioningConfig from a JSONB dict."""
    return models.ProvisioningConfig(
        placeholder_count=data["placeholder_count"],
        cpu_request=data["cpu_request"],
        memory_request=data["memory_request"],
        priority_class_name=data.get("priority_class_name"),
        lead_time_minutes=data["lead_time_minutes"],
        scale_down_behavior=models.ScaleDownBehavior(data["scale_down_behavior"]),
    )


def _matching_to_dict(matching: models.MatchingConfig) -> dict[str, Any]:
    """Serialize a MatchingConfig to a dict for JSONB storage."""
    return {
        "project_template_id": str(matching.project_template_id) if matching.project_template_id else None,
        "resource_class_id": matching.resource_class_id,
    }


def _matching_from_dict(data: dict[str, Any]) -> models.MatchingConfig:
    """Deserialize a MatchingConfig from a JSONB dict."""
    project_template_id = data.get("project_template_id")
    return models.MatchingConfig(
        project_template_id=ULID.from_str(project_template_id) if project_template_id else None,
        resource_class_id=data.get("resource_class_id"),
    )


class CapacityReservationORM(BaseORM):
    """The capacity reservations."""

    __tablename__ = "capacity_reservations"

    id: Mapped[ULID] = mapped_column(
        "id", ULIDType, primary_key=True, server_default=text("generate_ulid()"), init=False
    )
    name: Mapped[str] = mapped_column("name", String(40), index=True)
    recurrence: Mapped[dict[str, Any]] = mapped_column("recurrence", JSONVariant)
    provisioning: Mapped[dict[str, Any]] = mapped_column("provisioning", JSONVariant)
    matching: Mapped[dict[str, Any]] = mapped_column("matching", JSONVariant)

    def dump(self) -> models.CapacityReservation:
        """Create a capacity reservation model from this ORM object."""
        return models.CapacityReservation(
            id=self.id,
            name=self.name,
            recurrence=_recurrence_from_dict(self.recurrence),
            provisioning=_provisioning_from_dict(self.provisioning),
            matching=_matching_from_dict(self.matching),
        )

    @classmethod
    def from_unsaved_model(cls, new_capacity_reservation: models.UnsavedCapacityReservation) -> CapacityReservationORM:
        """Create an ORM object from an unsaved capacity reservation model."""
        return cls(
            name=new_capacity_reservation.name,
            recurrence=_recurrence_to_dict(new_capacity_reservation.recurrence),
            provisioning=_provisioning_to_dict(new_capacity_reservation.provisioning),
            matching=_matching_to_dict(new_capacity_reservation.matching),
        )


class OccurrenceORM(BaseORM):
    """The occurrences of capacity reservations."""

    __tablename__ = "occurrences"

    id: Mapped[ULID] = mapped_column(
        "id", ULIDType, primary_key=True, server_default=text("generate_ulid()"), init=False
    )
    reservation_id: Mapped[ULID] = mapped_column(
        "reservation_id",
        ULIDType,
        ForeignKey("capacity_reservation.capacity_reservations.id", ondelete="CASCADE"),
    )
    activate_at_datetime: Mapped[datetime] = mapped_column("activate_at_datetime", DateTime(timezone=True))
    start_datetime: Mapped[datetime] = mapped_column("start_datetime", DateTime(timezone=True))
    end_datetime: Mapped[datetime] = mapped_column("end_datetime", DateTime(timezone=True))
    status: Mapped[models.OccurrenceState] = mapped_column(
        "status", Enum(models.OccurrenceState, name="occurrence_state")
    )
    deployment_name: Mapped[Optional[str]] = mapped_column("deployment_name", String(255), nullable=True, default=None)

    def dump(self) -> models.Occurrence:
        """Create an occurrence model from this ORM object."""
        return models.Occurrence(
            id=self.id,
            reservation_id=self.reservation_id,
            activate_at_datetime=self.activate_at_datetime,
            start_datetime=self.start_datetime,
            end_datetime=self.end_datetime,
            status=self.status,
            deployment_name=self.deployment_name,
        )

    @classmethod
    def from_unsaved_model(cls, new_occurrence: models.UnsavedOccurrence) -> OccurrenceORM:
        """Create an ORM object from an unsaved occurrence model."""
        return cls(
            reservation_id=new_occurrence.reservation_id,
            activate_at_datetime=new_occurrence.activate_at_datetime,
            start_datetime=new_occurrence.start_datetime,
            end_datetime=new_occurrence.end_datetime,
            status=new_occurrence.status,
            deployment_name=new_occurrence.deployment_name,
        )
