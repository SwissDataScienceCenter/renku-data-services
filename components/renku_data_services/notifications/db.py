"""Adapters for notification database classes."""

import logging
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from renku_data_services import base_models, errors
from renku_data_services.notifications import models
from renku_data_services.notifications import orm as schemas
from renku_data_services.users.orm import UserORM

logger = logging.getLogger(__name__)


class NotificationsRepository:
    """Repository for Notifications."""

    def __init__(
        self,
        session_maker: Callable[..., AsyncSession],
        alertmanager_webhook_role: str = "alertmanager-webhook",
    ):
        self.session_maker = session_maker
        self.alertmanager_webhook_role = alertmanager_webhook_role

    async def create_alert(self, user: base_models.APIUser, alert: models.UnsavedAlert) -> models.Alert:
        """Insert a new alert into the database."""
        if user.id is None:
            raise errors.UnauthorizedError(message="You do not have the required permissions for this operation.")
        if not user.is_admin and self.alertmanager_webhook_role not in user.roles:
            raise errors.ForbiddenError(message="You do not have the required permissions for this operation.")

        async with self.session_maker() as session, session.begin():
            user_exists = await session.scalar(select(UserORM.keycloak_id).where(UserORM.keycloak_id == alert.user_id))
            if user_exists is None:
                raise errors.ValidationError(message=f"User with ID '{alert.user_id}' does not exist.")

            query = (
                select(schemas.AlertORM)
                .where(schemas.AlertORM.user_id == alert.user_id)
                .where(schemas.AlertORM.event_type == alert.event_type)
                .where(schemas.AlertORM.session_name == alert.session_name)
                .where(schemas.AlertORM.resolved_date.is_(None))
            )

            res = await session.scalars(query)
            existing_alert = res.one_or_none()
            if existing_alert is not None:
                raise errors.ConflictError(message="An identical unresolved alert already exists.")

            alert_orm = schemas.AlertORM(
                title=alert.title,
                message=alert.message,
                event_type=alert.event_type,
                user_id=alert.user_id,
                session_name=alert.session_name,
            )
            session.add(alert_orm)
            await session.flush()
            await session.refresh(alert_orm)
            return alert_orm.dump()

    async def get_alerts_for_user(
        self, user: base_models.APIUser, session_name: str | None = None
    ) -> list[models.Alert]:
        """Get all alerts for a given user."""
        if user.id is None:
            raise errors.UnauthorizedError(message="You do not have the required permissions for this operation.")

        async with self.session_maker() as session:
            query = (
                select(schemas.AlertORM)
                .where(schemas.AlertORM.user_id == user.id)
                .where(schemas.AlertORM.resolved_date.is_(None))
            )

            if session_name is not None:
                query = query.where(schemas.AlertORM.session_name == session_name)

            query = query.order_by(schemas.AlertORM.id.desc())
            alerts = await session.scalars(query)
            alert_list = alerts.all()
            return [alert.dump() for alert in alert_list]

    async def update_alert(self, user: base_models.APIUser, alert_id: ULID, patch: models.AlertPatch) -> models.Alert:
        """Update an existing alert in the database."""
        if user.id is None:
            raise errors.UnauthorizedError(message="You do not have the required permissions for this operation.")
        if not user.is_admin and self.alertmanager_webhook_role not in user.roles:
            raise errors.ForbiddenError(message="You do not have the required permissions for this operation.")

        async with self.session_maker() as session, session.begin():
            res = await session.scalars(select(schemas.AlertORM).where(schemas.AlertORM.id == alert_id))
            alert_orm = res.one_or_none()
            if alert_orm is None:
                raise errors.MissingResourceError(message=f"Alert with id '{alert_id}' not found.")

            self.__update_alert(alert_orm, patch)
            return alert_orm.dump()

    def __update_alert(self, alert: schemas.AlertORM, update: models.AlertPatch) -> None:
        if update.resolved is True:
            alert.resolved_date = datetime.now(UTC)

    async def get_alerts_by_properties(
        self,
        user: base_models.APIUser,
        alert_id: ULID | None,
        title: str | None,
        message: str | None,
        session_name: str | None,
        created_at: datetime | None,
        resolved_date: datetime | None,
    ) -> list[models.Alert]:
        """Get alerts by their properties."""
        if user.id is None:
            raise errors.UnauthorizedError(message="You do not have the required permissions for this operation.")

        async with self.session_maker() as session:
            query = select(schemas.AlertORM)

            if alert_id is not None:
                query = query.where(schemas.AlertORM.id == alert_id)

            if created_at is not None:
                query = query.where(schemas.AlertORM.creation_date == created_at)

            if title is None:
                query = query.where(schemas.AlertORM.title.is_(None))
            else:
                query = query.where(schemas.AlertORM.title == title)

            if message is None:
                query = query.where(schemas.AlertORM.message.is_(None))
            else:
                query = query.where(schemas.AlertORM.message == message)

            if resolved_date is None:
                query = query.where(schemas.AlertORM.resolved_date.is_(None))
            else:
                query = query.where(schemas.AlertORM.resolved_date == resolved_date)

            if session_name is None:
                query = query.where(schemas.AlertORM.session_name.is_(None))
            else:
                query = query.where(schemas.AlertORM.session_name == session_name)

            res = await session.scalars(query)
            alert_list = res.all()
            return [alert.dump() for alert in alert_list]

    async def create_or_update_alert(
        self, user: base_models.APIUser, alert: models.UnsavedAlert
    ) -> models.Alert | None:
        """Create a new alert or update an existing unresolved alert with the same properties.

        Returns None if the target user doesn't exist in the database.
        """

        if user.id is None:
            raise errors.UnauthorizedError(message="You do not have the required permissions for this operation.")
        if not user.is_admin and self.alertmanager_webhook_role not in user.roles:
            raise errors.ForbiddenError(message="You do not have the required permissions for this operation.")

        async with self.session_maker() as session, session.begin():
            user_exists = await session.scalar(select(UserORM.keycloak_id).where(UserORM.keycloak_id == alert.user_id))
            if user_exists is None:
                logger.warning("User with ID '%s' does not exist, skipping alert creation.", alert.user_id)
                return None

            query = (
                select(schemas.AlertORM)
                .where(schemas.AlertORM.user_id == alert.user_id)
                .where(schemas.AlertORM.event_type == alert.event_type)
                .where(schemas.AlertORM.resolved_date.is_(None))
            )

            if alert.session_name is not None:
                query = query.where(schemas.AlertORM.session_name == alert.session_name)

            res = await session.scalars(query)
            existing_alert = res.one_or_none()

            if existing_alert is not None:
                existing_alert.title = alert.title
                existing_alert.message = alert.message
                await session.flush()
                await session.refresh(existing_alert)
                return existing_alert.dump()

            alert_orm = schemas.AlertORM(
                title=alert.title,
                message=alert.message,
                event_type=alert.event_type,
                user_id=alert.user_id,
                session_name=alert.session_name,
            )
            session.add(alert_orm)
            await session.flush()
            await session.refresh(alert_orm)
            return alert_orm.dump()

    async def process_alertmanager_webhook(
        self,
        user: base_models.APIUser,
        firing_alerts: list[models.UnsavedAlert],
        resolved_alerts: list[models.UnsavedAlert],
    ) -> None:
        """Process firing and resolved alerts from an Alertmanager webhook.

        Firing alerts are created or updated. Resolved alerts are matched and marked as resolved.
        """
        for alert in firing_alerts:
            try:
                await self.create_or_update_alert(user=user, alert=alert)
            except Exception as e:
                logger.warning("Failed to create/update alert: %s. Error: %s", alert, e)

        for alert in resolved_alerts:
            try:
                matching_alerts = await self.get_alerts_by_properties(
                    user=user,
                    alert_id=None,
                    user_id=alert.user_id,
                    session_name=alert.session_name,
                    title=alert.title,
                    message=alert.message,
                    created_at=None,
                    resolved_date=None,
                )

                for matching_alert in matching_alerts:
                    patch = models.AlertPatch(resolved=True)
                    try:
                        await self.update_alert(user=user, alert_id=matching_alert.id, patch=patch)
                    except Exception as e:
                        logger.warning("Failed to resolve alert %s: %s", matching_alert.id, e)
            except Exception as e:
                logger.warning("Failed to process resolved alert: %s. Error: %s", alert, e)
