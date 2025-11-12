"""Adapters for notification database classes."""

from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from renku_data_services import base_models, errors
from renku_data_services.notifications import models
from renku_data_services.notifications import orm as schemas


class NotificationsRepository:
    """Repository for Notifications."""

    def __init__(
        self,
        session_maker: Callable[..., AsyncSession],
    ):
        self.session_maker = session_maker

    async def create_alert(self, user: base_models.APIUser, alert: models.UnsavedAlert) -> models.Alert:
        """Insert a new alert into the database."""
        if user.id is None:
            raise errors.UnauthorizedError(message="You do not have the required permissions for this operation.")
        if not user.is_admin:
            raise errors.ForbiddenError(message="You do not have the required permissions for this operation.")

        async with self.session_maker() as session:
            query = (
                select(schemas.AlertORM)
                .where(schemas.AlertORM.user_id == alert.user_id)
                .where(schemas.AlertORM.title == alert.title)
                .where(schemas.AlertORM.message == alert.message)
                .where(schemas.AlertORM.session_name == alert.session_name)
                .where(schemas.AlertORM.resolved_at.is_(None))
            )

            res = await session.scalars(query)
            existing_alert = res.one_or_none()
            if existing_alert is not None:
                raise errors.ConflictError(message="An identical unresolved alert already exists.")

        async with self.session_maker() as session, session.begin():
            alert_orm = schemas.AlertORM(
                title=alert.title,
                message=alert.message,
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
                .where(schemas.AlertORM.resolved_at.is_(None))
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
        if not user.is_admin:
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
            alert.resolved_at = datetime.now(UTC)
