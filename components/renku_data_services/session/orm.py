"""SQLAlchemy's schemas for the sessions database."""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, MetaData, String
from sqlalchemy.orm import DeclarativeBase, Mapped, MappedAsDataclass, mapped_column, relationship
from sqlalchemy.schema import ForeignKey
from ulid import ULID

from renku_data_services.project.orm import ProjectORM
from renku_data_services.session import models
from renku_data_services.session.apispec import EnvironmentKind

metadata_obj = MetaData(schema="sessions")  # Has to match alembic ini section name


class BaseORM(MappedAsDataclass, DeclarativeBase):
    """Base class for all ORM classes."""

    metadata = metadata_obj


class SessionEnvironmentORM(BaseORM):
    """A Renku 1.0 session environment."""

    __tablename__ = "environments"

    id: Mapped[str] = mapped_column("id", String(26), primary_key=True, default_factory=lambda: str(ULID()), init=False)
    """Id of this session environment object."""

    name: Mapped[str] = mapped_column("name", String(99))
    """Name of the session environment."""

    created_by_id: Mapped[str] = mapped_column("created_by_id", String())
    """Id of the user who created the session environment."""

    creation_date: Mapped[datetime] = mapped_column("creation_date", DateTime(timezone=True))
    """Creation date and time."""

    description: Mapped[Optional[str]] = mapped_column("description", String(500))
    """Human-readable description of the session environment."""

    container_image: Mapped[str] = mapped_column("container_image", String(500))
    """Container image repository and tag."""

    @classmethod
    def load(cls, environment: models.SessionEnvironment):
        """Create SessionEnvironmentORM from the session environment model."""
        return cls(
            name=environment.name,
            created_by_id=environment.created_by.id,
            creation_date=environment.creation_date,
            description=environment.description,
            container_image=environment.container_image,
        )

    def dump(self) -> models.SessionEnvironment:
        """Create a session environment model from the SessionEnvironmentORM."""
        return models.SessionEnvironment(
            id=self.id,
            name=self.name,
            created_by=models.Member(id=self.created_by_id),
            creation_date=self.creation_date,
            description=self.description,
            container_image=self.container_image,
        )


class SessionLauncherORM(BaseORM):
    """A Renku 1.0 session launcher."""

    __tablename__ = "launchers"

    id: Mapped[str] = mapped_column("id", String(26), primary_key=True, default_factory=lambda: str(ULID()), init=False)
    """Id of this session launcher object."""

    name: Mapped[str] = mapped_column("name", String(99))
    """Name of the session launcher."""

    created_by_id: Mapped[str] = mapped_column("created_by_id", String())
    """Id of the user who created the session launcher."""

    creation_date: Mapped[datetime] = mapped_column("creation_date", DateTime(timezone=True))
    """Creation date and time."""

    description: Mapped[Optional[str]] = mapped_column("description", String(500))
    """Human-readable description of the session launcher."""

    environment_kind: Mapped[EnvironmentKind]
    """The kind of environment definition to use."""

    container_image: Mapped[Optional[str]] = mapped_column("container_image", String(500))
    """Container image repository and tag."""

    project: Mapped[ProjectORM] = relationship(init=False)
    environment: Mapped[Optional[SessionEnvironmentORM]] = relationship(init=False)

    project_id: Mapped[str] = mapped_column(
        "project_id", ForeignKey(ProjectORM.id, ondelete="CASCADE"), default=None, index=True
    )
    """Id of the project this session belongs to."""

    environment_id: Mapped[Optional[str]] = mapped_column(
        "environment_id", ForeignKey(SessionEnvironmentORM.id), default=None, nullable=True, index=True
    )
    """Id of the session environment."""

    @classmethod
    def load(cls, launcher: models.SessionLauncher):
        """Create SessionLauncherORM from the session launcher model."""
        return cls(
            name=launcher.name,
            created_by_id=launcher.created_by.id,
            creation_date=launcher.creation_date,
            description=launcher.description,
            environment_kind=launcher.environment_kind,
            container_image=launcher.container_image,
            project_id=launcher.project_id,
            environment_id=launcher.environment_id,
        )

    def dump(self) -> models.SessionLauncher:
        """Create a session launcher model from the SessionLauncherORM."""
        return models.SessionLauncher(
            id=self.id,
            project_id=self.project_id,
            name=self.name,
            created_by=models.Member(id=self.created_by_id),
            creation_date=self.creation_date,
            description=self.description,
            environment_kind=self.environment_kind,
            environment_id=self.environment_id if self.environment_id is not None else None,
            container_image=self.container_image,
        )
