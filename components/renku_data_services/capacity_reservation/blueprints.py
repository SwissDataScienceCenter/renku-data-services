"""Capacity reservation blueprints."""

from dataclasses import dataclass

from sanic import Request, HTTPResponse
from sanic.response import JSONResponse
from sanic_ext import validate
from ulid import ULID

import renku_data_services.base_models as base_models
from renku_data_services.base_api.auth import (
    authenticate,
    only_admins,
)
from renku_data_services.base_api.blueprint import BlueprintFactoryResponse, CustomBlueprint
from renku_data_services.base_models.validation import validated_json
from renku_data_services.capacity_reservation import apispec
from renku_data_services.capacity_reservation.core import (
    validate_capacity_reservation,
)
from renku_data_services.capacity_reservation.db import CapacityReservationRepository


@dataclass(kw_only=True)
class CapacityReservationBP(CustomBlueprint):
    """Handlers for capacity reservations."""

    capacity_reservation_repo: CapacityReservationRepository
    authenticator: base_models.Authenticator

    def post(self) -> BlueprintFactoryResponse:
        """Create a new capacity reservation."""

        @authenticate(self.authenticator)
        @only_admins
        @validate(json=apispec.CapacityReservationPost)
        async def _post(_: Request, user: base_models.APIUser, body: apispec.CapacityReservationPost) -> JSONResponse:
            new_reservation = validate_capacity_reservation(body)
            reservation = await self.capacity_reservation_repo.create_capacity_reservation(
                user=user, capacity_reservation=new_reservation
            )
            return validated_json(apispec.CapacityReservation, reservation, 201)

        return "/capacity-reservations", ["POST"], _post

    def get_all(self) -> BlueprintFactoryResponse:
        """Get all capacity reservations."""

        @authenticate(self.authenticator)
        @only_admins
        async def _get_all(_: Request, user: base_models.APIUser) -> JSONResponse:
            reservations = await self.capacity_reservation_repo.get_capacity_reservations(user=user)
            return validated_json(apispec.CapacityReservationList, reservations)

        return "/capacity-reservations", ["GET"], _get_all

    def delete(self) -> BlueprintFactoryResponse:
        """Delete a capacity reservation by ID."""

        @authenticate(self.authenticator)
        @only_admins
        async def _delete(_: Request, user: base_models.APIUser, reservation_id: ULID) -> HTTPResponse:
            await self.capacity_reservation_repo.delete_capacity_reservation(
                user=user, capacity_reservation_id=reservation_id
            )
            return HTTPResponse(status=204)

        return "/capacity-reservations/<reservation_id:ulid>", ["DELETE"], _delete
