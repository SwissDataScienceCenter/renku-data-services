"""SQLAlchemy schemas for the peristed logs database."""

from __future__ import annotations

from sqlalchemy import BigInteger, ForeignKey, MetaData
from sqlalchemy.orm import DeclarativeBase, Mapped, MappedAsDataclass, mapped_column, relationship
from ulid import ULID

from renku_data_services.base_orm.registry import COMMON_ORM_REGISTRY
from renku_data_services.session.orm import SessionLauncherORM
from renku_data_services.users.orm import UserORM
from renku_data_services.utils.sqlalchemy import ULIDType


class BaseORM(MappedAsDataclass, DeclarativeBase):
    """Base class for all ORM classes."""

    metadata = MetaData(schema="persisted_logs")
    registry = COMMON_ORM_REGISTRY


class SessionRunsORM(BaseORM):
    """A session run, which is the continuous execution of a session."""

    __tablename__ = "session_runs"

    id: Mapped[ULID] = mapped_column("id", ULIDType, primary_key=True)
    """ID of a session run."""

    user_id: Mapped[str] = mapped_column(ForeignKey(UserORM.keycloak_id), index=True, nullable=False)
    """User ID of the owner of the session."""

    launch_id: Mapped[str] = mapped_column(nullable=False)
    """The launch ID for this session run."""

    launcher_id: Mapped[ULID] = mapped_column(ULIDType, ForeignKey(SessionLauncherORM.id), index=True, nullable=False)
    """The session launcher ID of the session."""

    submission_id: Mapped[str | None] = mapped_column(nullable=True)
    """The submission ID, if the session run corresponds to an offline job."""


class AmaltheaSessionLogsORM(BaseORM):
    """A log line from an Amalthea session."""

    __tablename__ = "amalthea_session_logs"

    id: Mapped[str] = mapped_column("id", primary_key=True, nullable=False)
    """ID of the log line."""

    run_id: Mapped[ULID] = mapped_column(ForeignKey(SessionRunsORM.id, ondelete="CASCADE"), index=True, nullable=False)
    """ID of the session run."""

    session_run: Mapped[SessionRunsORM] = relationship(lazy="select", init=False, repr=False, viewonly=True)
    """The session run this log line belongs to."""

    container: Mapped[str] = mapped_column(nullable=False)
    """The container this log line belongs to."""

    timestamp: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    """The timestamp of the log line (nanosecond timestamp)."""

    log_line: Mapped[str] = mapped_column(nullable=False)
    """The contents of the log line."""
