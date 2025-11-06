"""Adapters for notification database classes."""

from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
            query = select(schemas.AlertORM).where(schemas.AlertORM.user_id == user.id)

            if session_name is not None:
                query = query.where(schemas.AlertORM.session_name == session_name)

            query = query.order_by(schemas.AlertORM.id.desc())
            alerts = await session.scalars(query)
            alert_list = alerts.all()
            return [alert.dump() for alert in alert_list]
