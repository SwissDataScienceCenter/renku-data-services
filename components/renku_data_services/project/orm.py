"""SQLAlchemy's schemas for the projects database."""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Index, Integer, MetaData, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, MappedAsDataclass, mapped_column, relationship
from sqlalchemy.schema import ForeignKey
from ulid import ULID

from renku_data_services.authz import models as authz_models
from renku_data_services.namespace.orm import NamespaceORM
from renku_data_services.project import models
from renku_data_services.project.apispec import Visibility

metadata_obj = MetaData(schema="projects")  # Has to match alembic ini section name


class BaseORM(MappedAsDataclass, DeclarativeBase):
    """Base class for all ORM classes."""

    metadata = metadata_obj


class ProjectORM(BaseORM):
    """A Renku native project."""

    __tablename__ = "projects"
    id: Mapped[str] = mapped_column("id", String(26), primary_key=True, default_factory=lambda: str(ULID()), init=False)
    name: Mapped[str] = mapped_column("name", String(99))
    visibility: Mapped[Visibility]
    created_by_id: Mapped[str] = mapped_column("created_by_id", String())
    description: Mapped[str | None] = mapped_column("description", String(500))
    # NOTE: The project slugs table has a foreign key from the projects table, but there is a stored procedure
    # triggered by the deletion of slugs to remove the project used by the slug. See migration 89aa4573cfa9.
    slug: Mapped["ProjectSlug"] = relationship(lazy="joined", init=False, repr=False, viewonly=True)
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

    def dump(self) -> models.Project:
        """Create a project model from the ProjectORM."""
        return models.Project(
            id=self.id,
            name=self.name,
            slug=self.slug.slug,
            namespace=self.slug.namespace.slug,
            visibility=authz_models.Visibility.PUBLIC
            if self.visibility == Visibility.public
            else authz_models.Visibility.PRIVATE,
            created_by=self.created_by_id,
            creation_date=self.creation_date,
            updated_at=self.updated_at,
            repositories=[models.Repository(r.url) for r in self.repositories],
            description=self.description,
        )


class ProjectRepositoryORM(BaseORM):
    """Renku project repositories."""

    __tablename__ = "projects_repositories"

    id: Mapped[int] = mapped_column("id", Integer, primary_key=True, default=None, init=False)
    url: Mapped[str] = mapped_column("url", String(2000))
    project_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), default=None, index=True
    )
    project: Mapped[Optional[ProjectORM]] = relationship(back_populates="repositories", default=None, repr=False)


class ProjectSlug(BaseORM):
    """Project and namespace slugs."""

    __tablename__ = "project_slugs"
    __table_args__ = (Index("project_slugs_unique_slugs", "namespace_id", "slug", unique=True),)

    id: Mapped[int] = mapped_column(primary_key=True, init=False)
    slug: Mapped[str] = mapped_column(String(99), index=True, nullable=False)
    project_id: Mapped[str] = mapped_column(
        ForeignKey(ProjectORM.id, ondelete="CASCADE", name="project_slugs_project_id_fk"), index=True
    )
    namespace_id: Mapped[str] = mapped_column(
        ForeignKey(NamespaceORM.id, ondelete="CASCADE", name="project_slugs_namespace_id_fk"), index=True
    )
    namespace: Mapped[NamespaceORM] = relationship(lazy="joined", init=False, repr=False, viewonly=True)


class ProjectSlugOld(BaseORM):
    """Project slugs history."""

    __tablename__ = "project_slugs_old"

    id: Mapped[int] = mapped_column(primary_key=True, init=False)
    slug: Mapped[str] = mapped_column(String(99), index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True, init=False, server_default=func.now()
    )
    latest_slug_id: Mapped[int] = mapped_column(
        ForeignKey(ProjectSlug.id, ondelete="CASCADE"),
        nullable=False,
        init=False,
        index=True,
    )
    latest_slug: Mapped[ProjectSlug] = relationship(lazy="joined", repr=False, viewonly=True)
