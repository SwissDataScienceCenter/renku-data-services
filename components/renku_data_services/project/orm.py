"""SQLAlchemy's schemas for the projects database."""

from datetime import datetime
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, DateTime, Identity, Index, Integer, MetaData, String, false, func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import DeclarativeBase, Mapped, MappedAsDataclass, mapped_column, relationship
from sqlalchemy.schema import ForeignKey, UniqueConstraint
from ulid import ULID

from renku_data_services.authz import models as authz_models
from renku_data_services.base_models.core import ProjectPath
from renku_data_services.base_orm.registry import COMMON_ORM_REGISTRY
from renku_data_services.namespace.models import ProjectNamespace
from renku_data_services.project import constants, models
from renku_data_services.project.apispec import Visibility
from renku_data_services.secrets.orm import SecretORM
from renku_data_services.users.orm import UserORM
from renku_data_services.utils.sanic_pgaudit import versioning_manager
from renku_data_services.utils.sqlalchemy import PurePosixPathType, ULIDType

if TYPE_CHECKING:
    from renku_data_services.namespace.orm import EntitySlugORM


class CommonORM(MappedAsDataclass, DeclarativeBase):
    """Base class for common schema."""

    metadata = MetaData(schema="common")
    registry = COMMON_ORM_REGISTRY


versioning_manager.init(CommonORM)


class BaseORM(MappedAsDataclass, DeclarativeBase):
    """Base class for all ORM classes."""

    metadata = MetaData(schema="projects")
    registry = COMMON_ORM_REGISTRY


class ProjectORM(BaseORM):
    """A Renku native project."""

    __tablename__ = "projects"
    __table_args__ = (Index("ix_projects_project_template_id", "template_id"),)
    __versioned__ = {"exclude": ["creation_date"]}
    id: Mapped[ULID] = mapped_column("id", ULIDType, primary_key=True, default_factory=lambda: str(ULID()), init=False)
    name: Mapped[str] = mapped_column("name", String(99))
    visibility: Mapped[Visibility]
    created_by_id: Mapped[str] = mapped_column("created_by_id", String())
    description: Mapped[str | None] = mapped_column("description", String(500))
    keywords: Mapped[Optional[list[str]]] = mapped_column("keywords", ARRAY(String(99)), nullable=True)
    documentation: Mapped[str | None] = mapped_column("documentation", String(), nullable=True, deferred=True)
    secrets_mount_directory: Mapped[PurePosixPath] = mapped_column("secrets_mount_directory", PurePosixPathType)
    """Location where secrets are mounted in this project's sessions."""
    # NOTE: The project slugs table has a foreign key from the projects table, but there is a stored procedure
    # triggered by the deletion of slugs to remove the project used by the slug. See migration 89aa4573cfa9.
    slug: Mapped["EntitySlugORM"] = relationship(
        lazy="joined",
        init=False,
        repr=False,
        viewonly=True,
        back_populates="project",
        # NOTE: If the data_connector ID is not null below then multiple joins are possible here
        # since an entity slug for data connector owned by a project and an entity slug for a project
        # will be in the same table.
        primaryjoin="and_(EntitySlugORM.project_id == ProjectORM.id, EntitySlugORM.data_connector_id.is_(None))",
    )
    repositories: Mapped[list["ProjectRepositoryORM"]] = relationship(
        back_populates="project",
        default_factory=list,
        cascade="save-update, merge, delete",
        lazy="selectin",
        repr=False,
    )
    creation_date: Mapped[datetime] = mapped_column(
        "creation_date", DateTime(timezone=True), default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        "updated_at", DateTime(timezone=True), default=None, server_default=func.now(), onupdate=func.now()
    )
    template_id: Mapped[Optional[ULID]] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), default=None)
    is_template: Mapped[bool] = mapped_column(
        "is_template", Boolean(), default=False, server_default=false(), nullable=False
    )
    """Indicates whether a project is a template project or not."""

    def dump(self, with_documentation: bool = False) -> models.Project:
        """Create a project model from the ProjectORM."""
        return models.Project(
            id=self.id,
            name=self.name,
            slug=self.slug.slug,
            namespace=self.slug.namespace.dump(),
            visibility=authz_models.Visibility.PUBLIC
            if self.visibility == Visibility.public
            else authz_models.Visibility.PRIVATE,
            created_by=self.created_by_id,
            creation_date=self.creation_date,
            updated_at=self.updated_at,
            repositories=[models.Repository(r.url) for r in self.repositories],
            description=self.description,
            keywords=self.keywords,
            documentation=self.documentation if with_documentation else None,
            template_id=self.template_id,
            is_template=self.is_template,
            secrets_mount_directory=self.secrets_mount_directory or constants.DEFAULT_SESSION_SECRETS_MOUNT_DIR,
        )

    def dump_as_namespace(self) -> ProjectNamespace:
        """Get the namespace representation of the project."""
        return ProjectNamespace(
            id=self.slug.namespace.id,
            created_by=self.created_by_id,
            underlying_resource_id=self.id,
            latest_slug=self.slug.slug,
            name=self.name,
            creation_date=self.creation_date,
            path=ProjectPath.from_strings(self.slug.namespace.slug, self.slug.slug),
        )


class ProjectRepositoryORM(BaseORM):
    """Renku project repositories."""

    __tablename__ = "projects_repositories"

    id: Mapped[int] = mapped_column("id", Integer, Identity(always=True), primary_key=True, default=None, init=False)
    url: Mapped[str] = mapped_column("url", String(2000))
    project_id: Mapped[Optional[ULID]] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), default=None, index=True
    )
    project: Mapped[Optional[ProjectORM]] = relationship(back_populates="repositories", default=None, repr=False)


class SessionSecretSlotORM(BaseORM):
    """A slot for a secret in a session."""

    __tablename__ = "session_secret_slots"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "filename",
            name="_unique_project_id_filename",
        ),
    )

    id: Mapped[ULID] = mapped_column("id", ULIDType, primary_key=True, default_factory=lambda: str(ULID()), init=False)
    """ID of this session secret slot."""

    project_id: Mapped[ULID] = mapped_column(ForeignKey(ProjectORM.id, ondelete="CASCADE"), index=True, nullable=False)
    """ID of the project."""
    project: Mapped[ProjectORM] = relationship(init=False, repr=False, lazy="selectin")

    name: Mapped[str] = mapped_column("name", String(99))
    """Name of the session secret slot."""

    description: Mapped[str | None] = mapped_column("description", String(500))
    """Human-readable description of the session secret slot."""

    filename: Mapped[str] = mapped_column("filename", String(200))
    """The filename given to the corresponding secret when mounted in the session."""

    created_by_id: Mapped[str] = mapped_column(ForeignKey(UserORM.keycloak_id), index=True, nullable=False)
    """User ID of the creator of the session secret slot."""

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

    def dump(self) -> models.SessionSecretSlot:
        """Create a session secret slot model from the SessionSecretSlotORM."""
        return models.SessionSecretSlot(
            id=self.id,
            project_id=self.project_id,
            name=self.name,
            description=self.description,
            filename=self.filename,
            created_by_id=self.created_by_id,
            creation_date=self.creation_date,
            updated_at=self.updated_at,
        )


class SessionSecretORM(BaseORM):
    """Secrets for a project's sessions."""

    __tablename__ = "session_secrets"
    __table_args__ = (
        UniqueConstraint(
            "secret_slot_id",
            "user_id",
            name="_unique_secret_slot_id_user_id",
        ),
    )

    id: Mapped[ULID] = mapped_column("id", ULIDType, primary_key=True, default_factory=lambda: str(ULID()), init=False)
    """ID of this session secret."""

    user_id: Mapped[str] = mapped_column(
        ForeignKey(UserORM.keycloak_id, ondelete="CASCADE"), index=True, nullable=False
    )

    secret_slot_id: Mapped[ULID] = mapped_column(
        "secret_slot_id", ForeignKey(SessionSecretSlotORM.id, ondelete="CASCADE")
    )
    secret_slot: Mapped[SessionSecretSlotORM] = relationship(init=False, repr=False, lazy="selectin")

    secret_id: Mapped[ULID] = mapped_column("secret_id", ForeignKey(SecretORM.id, ondelete="CASCADE"))
    secret: Mapped[SecretORM] = relationship(init=False, repr=False, back_populates="session_secrets", lazy="selectin")

    def dump(self) -> models.SessionSecret:
        """Create a session secret model from the SessionSecretORM."""
        return models.SessionSecret(
            secret_slot=self.secret_slot.dump(),
            secret_id=self.secret_id,
        )


class ProjectMigrationsORM(BaseORM):
    """Tracks project migrations from an old project (project_v1_id) to a new project (project_id)."""

    __tablename__ = "project_migrations"
    __table_args__ = (UniqueConstraint("project_v1_id", name="uq_project_v1_id"),)

    id: Mapped[ULID] = mapped_column("id", ULIDType, primary_key=True, default_factory=lambda: str(ULID()), init=False)

    project_v1_id: Mapped[int] = mapped_column("project_v1_id", Integer, nullable=False, unique=True)
    """The old project being migrated. Must be unique."""

    project_id: Mapped[ULID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    """The new project of the migration of the v1."""

    project: Mapped[ProjectORM] = relationship(init=False, repr=False, lazy="selectin")
    """Relationship to the new project."""

    launcher_id: Mapped[Optional[ULID]] = mapped_column(ULIDType, nullable=True, default=None)
    """Stores the launcher ID without enforcing a foreign key."""
