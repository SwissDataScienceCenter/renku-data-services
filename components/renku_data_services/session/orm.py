"""SQLAlchemy's schemas for the sessions database."""

from datetime import datetime
from pathlib import PurePosixPath

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Identity,
    Integer,
    MetaData,
    String,
    false,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, MappedAsDataclass, mapped_column, relationship
from sqlalchemy.schema import ForeignKey
from ulid import ULID

from renku_data_services import errors
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
    working_directory: Mapped[PurePosixPath | None] = mapped_column(
        "working_directory", PurePosixPathType, nullable=True
    )
    mount_directory: Mapped[PurePosixPath | None] = mapped_column("mount_directory", PurePosixPathType, nullable=True)
    uid: Mapped[int] = mapped_column("uid")
    gid: Mapped[int] = mapped_column("gid")
    environment_kind: Mapped[models.EnvironmentKind] = mapped_column("environment_kind")
    environment_image_source: Mapped[models.EnvironmentImageSource] = mapped_column(
        "environment_image_source", server_default="image", nullable=False
    )

    args: Mapped[list[str] | None] = mapped_column("args", JSONVariant, nullable=True)
    command: Mapped[list[str] | None] = mapped_column("command", JSONVariant, nullable=True)

    creation_date: Mapped[datetime] = mapped_column(
        "creation_date", DateTime(timezone=True), default=func.now(), nullable=False
    )
    """Creation date and time."""

    is_archived: Mapped[bool] = mapped_column(
        "is_archived", Boolean(), default=False, server_default=false(), nullable=False
    )

    build_parameters_id: Mapped[ULID | None] = mapped_column(
        "build_parameters_id",
        ForeignKey("build_parameters.id", ondelete="CASCADE", name="environments_build_parameters_id_fk"),
        nullable=True,
        server_default=None,
        default=None,
    )
    build_parameters: Mapped["BuildParametersORM"] = relationship(lazy="joined", default=None)
    strip_path_prefix: Mapped[bool] = mapped_column(default=False, server_default=false(), nullable=False)

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
            is_archived=self.is_archived,
            environment_image_source=self.environment_image_source,
            build_parameters=self.build_parameters.dump() if self.build_parameters else None,
            build_parameters_id=self.build_parameters_id,
            strip_path_prefix=self.strip_path_prefix,
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

    disk_storage: Mapped[int | None] = mapped_column("disk_storage", BigInteger, default=None, nullable=True)
    """Default value for requested disk storage."""

    env_variables: Mapped[dict[str, str | None] | None] = mapped_column(
        "env_variables", JSONVariant, default=None, nullable=True
    )
    """Environment variables to set in the session."""

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
            disk_storage=launcher.disk_storage,
            env_variables=models.EnvVar.to_dict(launcher.env_variables) if launcher.env_variables else None,
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
            disk_storage=self.disk_storage,
            env_variables=models.EnvVar.from_dict(self.env_variables) if self.env_variables else None,
            environment=self.environment.dump(),
        )


class BuildParametersORM(BaseORM):
    """A Renku 2.0 session build parameters."""

    __tablename__ = "build_parameters"

    id: Mapped[ULID] = mapped_column("id", ULIDType, primary_key=True, default_factory=lambda: str(ULID()), init=False)
    """Id of this session build parameters object."""

    repository: Mapped[str] = mapped_column("repository", String(500))

    builder_variant: Mapped[str] = mapped_column("builder_variant", String(99))

    frontend_variant: Mapped[str] = mapped_column("frontend_variant", String(99))

    repository_revision: Mapped[str | None] = mapped_column(
        "repository_revision", String(500), nullable=True, default=None
    )

    context_dir: Mapped[str | None] = mapped_column("context_dir", String(500), nullable=True, default=None)

    platforms: Mapped[list["BuildPlatformORM"]] = relationship(
        back_populates="build_parameters",
        default_factory=list,
        cascade="save-update, merge, delete, delete-orphan",
        lazy="selectin",
        order_by="BuildPlatformORM.platform",
    )

    def dump(self) -> models.BuildParameters:
        """Create a session build parameters model from the BuildParametersORM."""
        platforms = [item.platform for item in self.platforms]
        return models.BuildParameters(
            id=self.id,
            platforms=platforms,
            repository=self.repository,
            builder_variant=self.builder_variant,
            frontend_variant=self.frontend_variant,
            repository_revision=self.repository_revision or None,
            context_dir=self.context_dir or None,
        )


class BuildPlatformORM(BaseORM):
    """The build platforms referenced by build parameters."""

    __tablename__ = "build_platforms"

    id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True, init=False)

    platform: Mapped[str] = mapped_column("platform", String(99))

    build_parameters_id: Mapped[ULID] = mapped_column(
        "build_parameters_id",
        ForeignKey(BuildParametersORM.id, ondelete="CASCADE", name="build_platform_build_parameters_id_fk"),
        init=False,
    )
    build_parameters: Mapped[BuildParametersORM] = relationship(back_populates="platforms", lazy="select", default=None)


class BuildORM(BaseORM):
    """A build of a container image."""

    __tablename__ = "builds"

    id: Mapped[ULID] = mapped_column("id", ULIDType, primary_key=True, default_factory=lambda: str(ULID()), init=False)
    """ID of this container image build."""

    environment_id: Mapped[ULID] = mapped_column("environment_id", ForeignKey(EnvironmentORM.id, ondelete="CASCADE"))
    environment: Mapped[EnvironmentORM] = relationship(init=False, repr=False, lazy="selectin")

    status: Mapped[models.BuildStatus] = mapped_column("status")

    created_at: Mapped[datetime] = mapped_column(
        "created_at", DateTime(timezone=True), default=func.now(), nullable=False
    )

    result_image: Mapped[str | None] = mapped_column("result_image", String(500), default=None)

    completed_at: Mapped[datetime | None] = mapped_column("completed_at", DateTime(timezone=True), default=None)

    result_repository_url: Mapped[str | None] = mapped_column("result_repository_url", String(500), default=None)

    result_repository_git_commit_sha: Mapped[str | None] = mapped_column(
        "result_repository_git_commit_sha", String(100), default=None
    )

    error_reason: Mapped[str | None] = mapped_column("error_reason", String(500), default=None)

    def dump(self) -> models.Build:
        """Create a build object from the ORM object."""
        result = self._dump_result()
        return models.Build(
            id=self.id,
            environment_id=self.environment_id,
            created_at=self.created_at,
            status=self.status,
            result=result,
            error_reason=self.error_reason,
        )

    def _dump_result(self) -> models.BuildResult | None:
        if self.status != models.BuildStatus.succeeded:
            return None
        if (
            self.result_image is None
            or self.completed_at is None
            or self.result_repository_url is None
            or self.result_repository_git_commit_sha is None
        ):
            raise errors.ProgrammingError(message=f"Build with id '{self.id}' is invalid.")
        return models.BuildResult(
            image=self.result_image,
            completed_at=self.completed_at,
            repository_url=self.result_repository_url,
            repository_git_commit_sha=self.result_repository_git_commit_sha,
        )
