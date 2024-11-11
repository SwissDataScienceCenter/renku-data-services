"""SQLAlchemy's schemas for the sessions database."""

from datetime import datetime
from pathlib import PurePosixPath

from sqlalchemy import JSON, DateTime, MetaData, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, MappedAsDataclass, mapped_column, relationship
from sqlalchemy.schema import ForeignKey
from ulid import ULID

from renku_data_services.base_orm.registry import COMMON_ORM_REGISTRY
from renku_data_services.crc.orm import ResourceClassORM
from renku_data_services.project.orm import ProjectORM
from renku_data_services.session import models
from renku_data_services.utils.sqlalchemy import PurePosixPathType, ULIDType

JSONVariant = JSON().with_variant(JSONB(), "postgresql")


class BaseORM(MappedAsDataclass, DeclarativeBase):
    """Base class for all ORM classes."""

    metadata = MetaData(schema="sessions")
    registry = COMMON_ORM_REGISTRY


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


class SessionLauncherSecretSlotORM(BaseORM):
    """A slot for a secret in a session launcher."""

    __tablename__ = "launcher_secret_slots"
    __table_args__ = (
        UniqueConstraint(
            "session_launcher_id",
            "filename",
            name="_unique_session_launcher_id_filename",
        ),
    )

    id: Mapped[ULID] = mapped_column("id", ULIDType, primary_key=True, default_factory=lambda: str(ULID()), init=False)
    """ID of this session launcher secret slot."""

    session_launcher_id: Mapped[ULID] = mapped_column(
        ForeignKey(SessionLauncherORM.id, ondelete="CASCADE"), index=True, nullable=False
    )
    """ID of the session launcher."""
    session_launcher: Mapped[SessionLauncherORM] = relationship(init=False, repr=False, lazy="selectin")

    name: Mapped[str] = mapped_column("name", String(99))
    """Name of the secret slot."""

    description: Mapped[str | None] = mapped_column("description", String(500))
    """Human-readable description of the secret slot."""

    filename: Mapped[str] = mapped_column("filename", String(200))
    """The filename given to the corresponding secret in the session."""

    created_by_id: Mapped[str] = mapped_column(ForeignKey(UserORM.keycloak_id), index=True, nullable=False)
    """User ID of the creator of the secret slot."""

    creation_date: Mapped[datetime] = mapped_column(
        "creation_date", DateTime(timezone=True), default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        "updated_at",
        DateTime(timezone=True),
        default=None,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def dump(self) -> models.SessionLauncherSecretSlot:
        """Create a secret slot model from the SessionLauncherSecretSlotORM."""
        return models.SessionLauncherSecretSlot(
            id=self.id,
            session_launcher_id=self.session_launcher_id,
            name=self.name,
            description=self.description,
            filename=self.filename,
            created_by_id=self.created_by_id,
            creation_date=self.creation_date,
            updated_at=self.updated_at,
        )


class SessionLauncherSecretORM(BaseORM):
    """Secrets for session launchers."""

    __tablename__ = "launcher_secrets"
    __table_args__ = (
        UniqueConstraint(
            "secret_slot_id",
            "user_id",
            name="_unique_secret_slot_id_user_id",
        ),
    )

    id: Mapped[ULID] = mapped_column("id", ULIDType, primary_key=True, default_factory=lambda: str(ULID()), init=False)
    """ID of this session launcher secret."""

    user_id: Mapped[str] = mapped_column(
        ForeignKey(UserORM.keycloak_id, ondelete="CASCADE"), index=True, nullable=False
    )

    secret_slot_id: Mapped[ULID] = mapped_column(
        "secret_slot_id", ForeignKey(SessionLauncherSecretSlotORM.id, ondelete="CASCADE")
    )
    secret_slot: Mapped[SessionLauncherSecretSlotORM] = relationship(init=False, repr=False, lazy="selectin")

    secret_id: Mapped[ULID] = mapped_column("secret_id", ForeignKey(SecretORM.id, ondelete="CASCADE"))
    secret: Mapped[SecretORM] = relationship(
        init=False, repr=False, back_populates="session_launcher_secrets", lazy="selectin"
    )

    def dump(self) -> models.SessionLauncherSecret:
        """Create a session launcher secret model from the SessionLauncherSecretORM."""
        return models.SessionLauncherSecret(
            secret_slot=self.secret_slot.dump(),
            secret_id=self.secret_id,
        )
