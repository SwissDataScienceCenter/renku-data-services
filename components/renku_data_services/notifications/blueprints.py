"""Notifications blueprint."""

from dataclasses import dataclass

from sanic import Request
from sanic.response import JSONResponse
from sanic_ext import validate

import renku_data_services.base_models as base_models

from renku_data_services.base_api.auth import (
    authenticate,
    only_admins,
)

from renku_data_services.base_api.blueprint import BlueprintFactoryResponse, CustomBlueprint
from renku_data_services.base_models.validation import validated_json

from renku_data_services.notifications import apispec
from renku_data_services.notifications.core import validate_unsaved_alert
from renku_data_services.notifications.db import NotificationsRepository


@dataclass(kw_only=True)
class NotificationsBP(CustomBlueprint):
    """Handlers for notifications."""

    notifications_repo: NotificationsRepository
    authenticator: base_models.Authenticator

    def post(self) -> BlueprintFactoryResponse:
        """Create a new alert."""

        @authenticate(self.authenticator)
        @only_admins
        @validate(json=apispec.AlertPost)
        async def _post(_: Request, user: base_models.APIUser, body: apispec.AlertPost) -> JSONResponse:
            new_alert = validate_unsaved_alert(body)
            alert = await self.notifications_repo.create_alert(user=user, alert=new_alert)
            return validated_json(apispec.Alert, alert, 201)

        return "/alerts", ["POST"], _post

    def get_all(self) -> BlueprintFactoryResponse:
        """Get all alerts for the authenticated user."""

        @authenticate(self.authenticator)
        async def _get_all(_: Request, user: base_models.APIUser) -> JSONResponse:
            alerts = await self.notifications_repo.get_alerts_for_user(user=user)
            return validated_json(apispec.AlertList, alerts)

        return "/alerts", ["GET"], _get_all
