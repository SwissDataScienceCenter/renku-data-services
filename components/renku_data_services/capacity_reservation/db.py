"""Adapters for capacity reservation database classes."""

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from renku_data_services import base_models, errors
from renku_data_services.capacity_reservation import models
from renku_data_services.capacity_reservation import orm as schemas

logger = logging.getLogger(__name__)


class CapacityReservationRepository:
    """Repository for Capacity Reservations."""

    def __init__(self, session_maker: Callable[..., AsyncSession]):
        self.session_maker = session_maker

    async def create_capacity_reservation(
        self, user: base_models.APIUser, capacity_reservation: models.UnsavedCapacityReservation
    ) -> models.CapacityReservation:
        """Insert a new capacity reservation into the database."""
        if user.id is None:
            raise errors.UnauthorizedError(message="You do not have the required permissions for this operation.")
        if not user.is_admin:
            raise errors.ForbiddenError(message="You do not have the required permissions for this operation.")

        async with self.session_maker() as session, session.begin():
            capacity_reservation_orm = schemas.CapacityReservationORM.from_unsaved_model(capacity_reservation)
            session.add(capacity_reservation_orm)
            await session.flush()
            await session.refresh(capacity_reservation_orm)
            return capacity_reservation_orm.dump()

    async def get_capacity_reservations(self, user: base_models.APIUser) -> list[models.CapacityReservation]:
        """Get all capacity reservations."""
        if user.id is None:
            raise errors.UnauthorizedError(message="You do not have the required permissions for this operation.")
        if not user.is_admin:
            raise errors.ForbiddenError(message="You do not have the required permissions for this operation.")

        async with self.session_maker() as session:
            query = select(schemas.CapacityReservationORM)

            capacity_reservations = await session.scalars(query)
            capacity_reservation_list = capacity_reservations.all()
            return [cr.dump() for cr in capacity_reservation_list]

    async def delete_capacity_reservation(self, user: base_models.APIUser, capacity_reservation_id: ULID) -> None:
        """Delete a capacity reservation by ID."""
        if user.id is None:
            raise errors.UnauthorizedError(message="You do not have the required permissions for this operation.")
        if not user.is_admin:
            raise errors.ForbiddenError(message="You do not have the required permissions for this operation.")

        async with self.session_maker() as session, session.begin():
            result = await session.execute(
                select(schemas.CapacityReservationORM).where(
                    schemas.CapacityReservationORM.id == capacity_reservation_id
                )
            )

            capacity_reservation = result.scalar_one_or_none()

            if capacity_reservation is None:
                return None

            await session.execute(
                delete(schemas.CapacityReservationORM).where(
                    schemas.CapacityReservationORM.id == capacity_reservation_id
                )
            )

        return None


class OccurrenceAdapter:
    """Repository for Occurrences."""

    def __init__(self, session_maker: Callable[..., AsyncSession]):
        self.session_maker = session_maker

    async def get_occurrences_by_properties(
        self,
        user: base_models.APIUser,
        id: ULID | None,
        reservation_id: ULID | None,
        status: models.OccurrenceState | None,
        start_datetime: datetime | None,
        starts_within_minutes: int | None,
        end_datetime: datetime | None,
        ends_within_minutes: int | None,
        deployment_name: str | None,
    ) -> list[models.Occurrence]:
        """Get occurrences by their properties."""

        if user.id is None:
            raise errors.UnauthorizedError(message="You do not have the required permissions for this operation.")
        if not user.is_admin:
            raise errors.ForbiddenError(message="You do not have the required permissions for this operation.")

        async with self.session_maker() as session:
            query = select(schemas.OccurrenceORM)

            if id is not None:
                query = query.where(schemas.OccurrenceORM.id == id)

            if reservation_id is not None:
                query = query.where(schemas.OccurrenceORM.reservation_id == reservation_id)

            if status is not None:
                query = query.where(schemas.OccurrenceORM.status == status)

            if start_datetime is not None and starts_within_minutes is not None:
                query = query.where(
                    schemas.OccurrenceORM.start_datetime.between(
                        start_datetime,
                        start_datetime + timedelta(minutes=starts_within_minutes),
                    )
                )
            elif start_datetime is not None:
                query = query.where(schemas.OccurrenceORM.start_datetime == start_datetime)
            elif starts_within_minutes is not None:
                query = query.where(
                    schemas.OccurrenceORM.start_datetime.between(
                        datetime.now(UTC),
                        datetime.now(UTC) + timedelta(minutes=starts_within_minutes),
                    )
                )

            if end_datetime is not None and ends_within_minutes is not None:
                query = query.where(
                    schemas.OccurrenceORM.end_datetime.between(
                        end_datetime,
                        end_datetime + timedelta(minutes=ends_within_minutes),
                    )
                )
            elif end_datetime is not None:
                query = query.where(schemas.OccurrenceORM.end_datetime == end_datetime)
            elif ends_within_minutes is not None:
                query = query.where(
                    schemas.OccurrenceORM.end_datetime.between(
                        datetime.now(UTC),
                        datetime.now(UTC) + timedelta(minutes=ends_within_minutes),
                    )
                )

            if deployment_name is not None:
                query = query.where(schemas.OccurrenceORM.deployment_name == deployment_name)

            occurrences = await session.scalars(query)
            occurrence_list = occurrences.all()
            return [occurrence.dump() for occurrence in occurrence_list]

    async def create_occurrences(self, occurrences: list[models.UnsavedOccurrence]) -> list[models.Occurrence]:
        """Insert new occurrences into the database."""

        async with self.session_maker() as session, session.begin():
            occurrence_orms = [schemas.OccurrenceORM.from_unsaved_model(occurrence) for occurrence in occurrences]
            session.add_all(occurrence_orms)
            await session.flush()
            for occurrence_orm in occurrence_orms:
                await session.refresh(occurrence_orm)
            return [occurrence_orm.dump() for occurrence_orm in occurrence_orms]

    async def update_occurrence(
        self,
        occurrence_id: ULID,
        occurrence_patch: models.OccurrencePatch,
    ) -> models.Occurrence:
        """Update an occurrence by ID."""

        async with self.session_maker() as session, session.begin():
            res = await session.scalars(select(schemas.OccurrenceORM).where(schemas.OccurrenceORM.id == occurrence_id))
            occurrence_orm = res.one_or_none()
            if occurrence_orm is None:
                raise errors.MissingResourceError(message=f"Occurrence with id {occurrence_id} not found.")

            if occurrence_patch.start_datetime is not None:
                occurrence_orm.start_datetime = occurrence_patch.start_datetime
            if occurrence_patch.end_datetime is not None:
                occurrence_orm.end_datetime = occurrence_patch.end_datetime
            if occurrence_patch.status is not None:
                occurrence_orm.status = occurrence_patch.status
            if occurrence_patch.deployment_name is not None:
                occurrence_orm.deployment_name = occurrence_patch.deployment_name
            await session.flush()
            await session.refresh(occurrence_orm)
            return occurrence_orm.dump()

    async def delete_occurrences(
        self,
        occurrences: list[models.Occurrence],
    ) -> None:
        """Delete multiple occurrences by their IDs."""

        if not occurrences:
            return

        occurrence_ids = [occurrence.id for occurrence in occurrences]

        async with self.session_maker() as session, session.begin():
            await session.execute(delete(schemas.OccurrenceORM).where(schemas.OccurrenceORM.id.in_(occurrence_ids)))
        return
