"""SQLAlchemy's schemas for the sessions database."""

from datetime import datetime

from sqlalchemy import DateTime, MetaData, String
from sqlalchemy.orm import DeclarativeBase, Mapped, MappedAsDataclass, mapped_column, relationship
from sqlalchemy.schema import ForeignKey
from ulid import ULID

from renku_data_services.crc.orm import ResourceClassORM
from renku_data_services.project.orm import ProjectORM
from renku_data_services.session import models
from renku_data_services.session.apispec import EnvironmentKind
from renku_data_services.utils.sqlalchemy import ULIDType

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

    default_url: Mapped[str | None] = mapped_column("default_url", String(200))
    """Default URL path to open in a session."""

    # @classmethod
    # def load(cls, environment: models.Environment) -> "EnvironmentORM":
    #     """Create EnvironmentORM from the session environment model."""
    #     return cls(
    #         name=environment.name,
    #         created_by_id=environment.created_by.id,
    #         creation_date=environment.creation_date,
    #         description=environment.description,
    #         container_image=environment.container_image,
    #         default_url=environment.default_url,
    #     )

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

    creation_date: Mapped[datetime] = mapped_column("creation_date", DateTime(timezone=True))
    """Creation date and time."""

    description: Mapped[str | None] = mapped_column("description", String(500))
    """Human-readable description of the session launcher."""

    environment_kind: Mapped[EnvironmentKind]
    """The kind of environment definition to use."""

    container_image: Mapped[str | None] = mapped_column("container_image", String(500))
    """Container image repository and tag."""

    default_url: Mapped[str | None] = mapped_column("default_url", String(200))
    """Default URL path to open in a session."""

    project: Mapped[ProjectORM] = relationship(init=False)
    environment: Mapped[EnvironmentORM | None] = relationship(init=False)

    project_id: Mapped[ULID] = mapped_column(
        "project_id", ForeignKey(ProjectORM.id, ondelete="CASCADE"), default=None, index=True
    )
    """Id of the project this session belongs to."""

    environment_id: Mapped[str | None] = mapped_column(
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
            environment_kind=launcher.environment_kind,
            container_image=launcher.container_image,
            project_id=ULID.from_str(launcher.project_id),
            environment_id=launcher.environment_id,
            resource_class_id=launcher.resource_class_id,
            default_url=launcher.default_url,
        )

    def dump(self) -> models.SessionLauncher:
        """Create a session launcher model from the SessionLauncherORM."""
        return models.SessionLauncher(
            id=self.id,
            project_id=str(self.project_id),
            name=self.name,
            created_by=models.Member(id=self.created_by_id),
            creation_date=self.creation_date,
            description=self.description,
            environment_kind=self.environment_kind,
            environment_id=self.environment_id if self.environment_id is not None else None,
            resource_class_id=self.resource_class_id if self.resource_class_id is not None else None,
            container_image=self.container_image,
            default_url=self.default_url,
        )
