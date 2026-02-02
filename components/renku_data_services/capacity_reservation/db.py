"""Adapters for capacity reservation database classes."""

import logging
from collections.abc import Callable

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from renku_data_services import base_models, errors
from renku_data_services.capacity_reservation import models
from renku_data_services.capacity_reservation import orm as schemas

logger = logging.getLogger(__name__)


class CapacityReservationAdapter:
    """Repository for Capacity Reservations"""

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
            query = (
                select(schemas.CapacityReservationORM)
                .where(schemas.CapacityReservationORM.name == capacity_reservation.name)
                .where(schemas.CapacityReservationORM.recurrence == capacity_reservation.recurrence)
                .where(schemas.CapacityReservationORM.provisioning == capacity_reservation.provisioning)
                .where(schemas.CapacityReservationORM.matching == capacity_reservation.matching)
            )

            res = await session.scalars(query)
            existing_capacity_reservation = res.one_or_none()
            if existing_capacity_reservation is not None:
                raise errors.ConflictError(message="An identical capacity reservation already exists.")

            capacity_reservation_orm = schemas.CapacityReservationORM.from_unsaved_model(capacity_reservation)

            capacity_reservation_orm = schemas.CapacityReservationORM(
                name=capacity_reservation.name,
                recurrence=capacity_reservation.recurrence,
                provisioning=capacity_reservation.provisioning,
                matching=capacity_reservation.matching,
            )
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
