"""SQLAlchemy schemas for the session runners database."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, MetaData, func, text
from sqlalchemy.orm import DeclarativeBase, Mapped, MappedAsDataclass, mapped_column, relationship
from ulid import ULID

from renku_data_services.base_orm.registry import COMMON_ORM_REGISTRY
from renku_data_services.crc.orm import ResourcePoolORM
from renku_data_services.session_runners import models
from renku_data_services.users.orm import UserORM
from renku_data_services.utils.sqlalchemy import ULIDType


class BaseORM(MappedAsDataclass, DeclarativeBase):
    """Base class for all ORM classes."""

    metadata = MetaData(schema="session_runners")
    registry = COMMON_ORM_REGISTRY


# Table: sessions_runners.runners
# - `id`: ULID of the runner
# - `user_id`: user ID who owns the runner
# - `resource_pool_id`: resource pool the runner is registered with
# - `status`: status of the runner
# - `resources`: available resources on the runner
# - `last_contact`: timestamp of the last contact
# - `registration_token`: random unique token for registration
class SessionRunnerORM(BaseORM):
    """A runner which can power a session in heterogeneous compute.

    At the moment, session runners are single user, i.e. they can run sessions
    for only one user.
    """

    __tablename__ = "runners"

    id: Mapped[ULID] = mapped_column(
        "id", ULIDType, primary_key=True, server_default=text("generate_ulid()"), init=False
    )
    """ID of a session runner."""

    user_id: Mapped[str] = mapped_column(
        ForeignKey(UserORM.keycloak_id, ondelete="CASCADE"), index=True, nullable=False
    )
    """User ID of the owner of the runner."""

    user: Mapped[UserORM] = relationship(init=False, repr=False)
    """The owner of the runner."""

    resource_pool_id: Mapped[int] = mapped_column(
        ForeignKey(ResourcePoolORM.id, ondelete="CASCADE"), index=True, nullable=False
    )
    """Resource pool ID the runner is registered with."""

    creation_date: Mapped[datetime] = mapped_column(
        "creation_date", DateTime(timezone=True), server_default=func.now(), nullable=False, init=False
    )
    """The creation date and time of the runner."""

    # TODO: registration_token: Mapped[str | None] = mapped_column(unique=True, nullable=True)
    registration_token: Mapped[str | None] = mapped_column(index=True, nullable=True)
    """The session UID for this session run."""

    status: Mapped[models.RunnerStatus] = mapped_column(
        "status",
        default=models.RunnerStatus.never_contacted,
        server_default=models.RunnerStatus.never_contacted.value,
        nullable=False,
    )
    """The status of the runner."""

    last_contact: Mapped[datetime] = mapped_column(
        "last_contact",
        DateTime(timezone=True),
        default=None,
        nullable=True,
    )
    """The date and time of the last contact with the runner."""

    def dump(self, include_registration_token: bool = False) -> models.SessionRunner:
        """Create a session runner model from the SessionRunnerORM."""
        return models.SessionRunner(
            id=self.id,
            resource_pool_id=self.resource_pool_id,
            status=self.status,
            registration_token=self.registration_token if include_registration_token else None,
        )
