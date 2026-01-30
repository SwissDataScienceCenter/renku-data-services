"""SQLAlchemy schemas for the capacity reservation database."""

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase, MappedAsDataclass
from ulid import ULID

from renku_data_services.capacity_reservation import models
from renku_data_services.utils.sqlalchemy import ULIDType

metadata_obj = MetaData(schema="capacity_reservation")


class BaseORM(MappedAsDataclass, DeclarativeBase):
    """Base class for all ORM classes."""

    metadata = metadata_obj


class CapacityReservationORM(BaseORM):
    """The capacity reservations."""

    __tablename__ = "capacity_reservations"

    id: Mapped[ULID] = mapped_column(
        "id", ULIDType, primary_key=True, server_default=text("generate_ulid()"), init=False
    )
    """ID of the capacity reservation."""

    name: Mapped[str] = mapped_column("name", String(40), index=true)
    """Name of the capacity reservation."""

    recurrence: Mapped[models.RecurrenceConfig] = mapped_column(
        "recurrence", postgresql.JSONB.as_mutable(models.RecurrenceConfigType)
    )
    """Recurrence configuration of the capacity reservation."""

    provisioning: Mapped[models.ProvisioningConfig] = mapped_column(
        "provisioning", postgresql.JSONB.as_mutable(models.ProvisioningConfigType)
    )
    """Provisioning configuration of the capacity reservation."""

    matching: Mapped[models.MatchingConfig] = mapped_column(
        "matching", postgresql.JSONB.as_mutable(models.MatchingConfigType)
    )
    """Matching configuration of the capacity reservation."""

    @classmethod
    def dump(self) -> base_models.CapacityReservation:
        "Create an ORM object from a capacity reservation model."
        return base_models.CapacityReservation(
            id=self.id,
            name=self.name,
            recurrence=self.recurrence,
            provisioning=self.provisioning,
            matching=self.matching,
        )

    def from_unsaved_model(
        cls, new_capacity_reservation: models.UnsavedCapacityReservation
    ) -> "CapacityReservationORM":
        "Create an ORM object from an unsaved capacity reservation model."
        return cls(
            name=new_capacity_reservation.name,
            recurrence=new_capacity_reservation.recurrence,
            provisioning=new_capacity_reservation.provisioning,
            matching=new_capacity_reservation.matching,
        )


class OccurrenceORM(BaseORM):
    """The occurrences of capacity reservations."""

    __tablename__ = "occurrences"

    id: Mapped[ULID] = mapped_column(
        "id", ULIDType, primary_key=True, server_default=text("generate_ulid()"), init=False
    )
    """ID of the occurrence."""
