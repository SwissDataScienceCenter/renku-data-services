"""SQLAlchemy's schemas for the sessions database."""

from datetime import datetime
from pathlib import PurePosixPath

from sqlalchemy import JSON, DateTime, MetaData, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, MappedAsDataclass, mapped_column, relationship
from sqlalchemy.schema import ForeignKey
from ulid import ULID

from renku_data_services.crc.orm import ResourceClassORM
from renku_data_services.project.orm import ProjectORM
from renku_data_services.session import models
from renku_data_services.utils.sqlalchemy import PurePosixPathType, ULIDType

metadata_obj = MetaData(schema="sessions")  # Has to match alembic ini section name
JSONVariant = JSON().with_variant(JSONB(), "postgresql")


class BaseORM(MappedAsDataclass, DeclarativeBase):
    """Base class for all ORM classes."""

    metadata = metadata_obj


class EnvironmentORM(BaseORM):
    """A Renku 2.0 session environment."""

    __tablename__ = "environments"

    id: Mapped[ULID] = mapped_column("id", ULIDType, primary_key=True, default_factory=lambda: str(ULID()), init=False)
    """Id of this session environment object."""

    name: Mapped[str] = mapped_column("name", String(99))
    """Name of the session environment."""

    created_by_id: Mapped[str] = mapped_column("created_by_id", String())
    """Id of the user who created the session environment."""

    description: Mapped[str | None] = mapped_column("description", String(500))
    """Human-readable description of the session environment."""

    container_image: Mapped[str] = mapped_column("container_image", String(500))
    """Container image repository and tag."""

    default_url: Mapped[str] = mapped_column("default_url", String(200))
    """Default URL path to open in a session."""

    port: Mapped[int] = mapped_column("port")
    working_directory: Mapped[PurePosixPath] = mapped_column("working_directory", PurePosixPathType)
    mount_directory: Mapped[PurePosixPath] = mapped_column("mount_directory", PurePosixPathType)
    uid: Mapped[int] = mapped_column("uid")
    gid: Mapped[int] = mapped_column("gid")
    environment_kind: Mapped[models.EnvironmentKind] = mapped_column("environment_kind")
    args: Mapped[list[str] | None] = mapped_column("args", JSONVariant, nullable=True)
    command: Mapped[list[str] | None] = mapped_column("command", JSONVariant, nullable=True)

    creation_date: Mapped[datetime] = mapped_column(
        "creation_date", DateTime(timezone=True), default=func.now(), nullable=False
    )
    """Creation date and time."""

    def dump(self) -> models.Environment:
        """Create a session environment model from the EnvironmentORM."""
        return models.Environment(
            id=self.id,
            name=self.name,
            created_by=models.Member(id=self.created_by_id),
            creation_date=self.creation_date,
            description=self.description,
            container_image=self.container_image,
            default_url=self.default_url,
            gid=self.gid,
            uid=self.uid,
            environment_kind=self.environment_kind,
            mount_directory=self.mount_directory,
            working_directory=self.working_directory,
            port=self.port,
            args=self.args,
            command=self.command,
        )


class SessionLauncherORM(BaseORM):
    """A Renku 2.0 session launcher."""

    __tablename__ = "launchers"

    id: Mapped[ULID] = mapped_column("id", ULIDType, primary_key=True, default_factory=lambda: str(ULID()), init=False)
    """Id of this session launcher object."""

    name: Mapped[str] = mapped_column("name", String(99))
    """Name of the session launcher."""

    created_by_id: Mapped[str] = mapped_column("created_by_id", String())
    """Id of the user who created the session launcher."""

    description: Mapped[str | None] = mapped_column("description", String(500))
    """Human-readable description of the session launcher."""

    project: Mapped[ProjectORM] = relationship(init=False)
    environment: Mapped[EnvironmentORM] = relationship(init=False, lazy="joined")

    creation_date: Mapped[datetime] = mapped_column(
        "creation_date", DateTime(timezone=True), default=func.now(), nullable=False
    )
    """Creation date and time."""

    project_id: Mapped[ULID] = mapped_column(
        "project_id", ForeignKey(ProjectORM.id, ondelete="CASCADE"), default=None, index=True
    )
    """Id of the project this session belongs to."""

    environment_id: Mapped[ULID] = mapped_column(
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

    @classmethod
    def load(cls, launcher: models.SessionLauncher) -> "SessionLauncherORM":
        """Create SessionLauncherORM from the session launcher model."""
        return cls(
            name=launcher.name,
            created_by_id=launcher.created_by.id,
            creation_date=launcher.creation_date,
            description=launcher.description,
            project_id=launcher.project_id,
            environment_id=launcher.environment.id,
            resource_class_id=launcher.resource_class_id,
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
            resource_class_id=self.resource_class_id,
            environment=self.environment.dump(),
        )
