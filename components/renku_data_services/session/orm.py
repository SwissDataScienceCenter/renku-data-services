"""SQLAlchemy's schemas for the sessions database."""

from datetime import datetime
from pathlib import PurePosixPath

from sqlalchemy import DateTime, MetaData, String
from sqlalchemy.orm import DeclarativeBase, Mapped, MappedAsDataclass, mapped_column, relationship
from sqlalchemy.schema import ForeignKey
from ulid import ULID

from renku_data_services.crc.orm import ResourceClassORM
from renku_data_services.project.orm import ProjectORM
from renku_data_services.session import models

metadata_obj = MetaData(schema="sessions")  # Has to match alembic ini section name


class BaseORM(MappedAsDataclass, DeclarativeBase):
    """Base class for all ORM classes."""

    metadata = metadata_obj


class EnvironmentORM(BaseORM):
    """A Renku 2.0 session environment."""

    __tablename__ = "environments"

    id: Mapped[str] = mapped_column("id", String(26), primary_key=True, default_factory=lambda: str(ULID()), init=False)
    """Id of this session environment object."""

    name: Mapped[str] = mapped_column("name", String(99))
    """Name of the session environment."""

    created_by_id: Mapped[str] = mapped_column("created_by_id", String())
    """Id of the user who created the session environment."""

    creation_date: Mapped[datetime] = mapped_column("creation_date", DateTime(timezone=True))
    """Creation date and time."""

    description: Mapped[str | None] = mapped_column("description", String(500))
    """Human-readable description of the session environment."""

    container_image: Mapped[str] = mapped_column("container_image", String(500))
    """Container image repository and tag."""

    default_url: Mapped[str] = mapped_column("default_url", String(200))
    """Default URL path to open in a session."""

    port: Mapped[int] = mapped_column("port")
    working_directory: Mapped[str] = mapped_column("working_directory", String())
    mount_directory: Mapped[str] = mapped_column("mount_directory", String())
    uid: Mapped[int] = mapped_column("uid")
    gid: Mapped[int] = mapped_column("gid")
    environment_kind: Mapped[models.EnvironmentKind] = mapped_column("environment_kind")

    def dump(self) -> models.Environment:
        """Create a session environment model from the EnvironmentORM."""
        return models.Environment(
            id=self.id,
            name=self.name,
            created_by=self.created_by_id,
            creation_date=self.creation_date,
            description=self.description,
            container_image=self.container_image,
            default_url=self.default_url,
            gid=self.gid,
            uid=self.uid,
            environment_kind=self.environment_kind,
            mount_directory=PurePosixPath(self.mount_directory),
            working_directory=PurePosixPath(self.working_directory),
            port=self.port,
        )


class SessionLauncherORM(BaseORM):
    """A Renku 2.0 session launcher."""

    __tablename__ = "launchers"

    id: Mapped[str] = mapped_column("id", String(26), primary_key=True, default_factory=lambda: str(ULID()), init=False)
    """Id of this session launcher object."""

    name: Mapped[str] = mapped_column("name", String(99))
    """Name of the session launcher."""

    created_by_id: Mapped[str] = mapped_column("created_by_id", String())
    """Id of the user who created the session launcher."""

    creation_date: Mapped[datetime] = mapped_column("creation_date", DateTime(timezone=True))
    """Creation date and time."""

    description: Mapped[str | None] = mapped_column("description", String(500))
    """Human-readable description of the session launcher."""

    project: Mapped[ProjectORM] = relationship(init=False)
    environment: Mapped[EnvironmentORM] = relationship(init=False)

    project_id: Mapped[str] = mapped_column(
        "project_id", ForeignKey(ProjectORM.id, ondelete="CASCADE"), default=None, index=True
    )
    """Id of the project this session belongs to."""

    environment_id: Mapped[str] = mapped_column(
        "environment_id", ForeignKey(EnvironmentORM.id), default=None, nullable=True, index=True
    )
    """Id of the session environment."""

    resource_class_id: Mapped[int | None] = mapped_column(
        "resource_class_id",
        ForeignKey(ResourceClassORM.id, ondelete="SET NULL"),
        default=None,
        nullable=True,
        index=False,
    )
    """Id of the resource class."""

    def dump(self) -> models.SessionLauncher:
        """Create a session launcher model from the SessionLauncherORM."""
        return models.SessionLauncher(
            id=self.id,
            project_id=self.project_id,
            name=self.name,
            created_by=self.created_by_id,
            creation_date=self.creation_date,
            description=self.description,
            environment=self.environment.dump(),
            resource_class_id=self.resource_class_id,
        )
