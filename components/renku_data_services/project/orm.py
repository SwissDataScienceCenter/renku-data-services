"""SQLAlchemy's schemas for the projects database."""

from datetime import datetime
from typing import List, Optional

from sqlalchemy import DateTime, Index, Integer, MetaData, String
from sqlalchemy import DateTime, Integer, MetaData, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, MappedAsDataclass, mapped_column, relationship
from sqlalchemy.schema import ForeignKey
from ulid import ULID

from renku_data_services.project import models
from renku_data_services.project.apispec import Visibility

metadata_obj = MetaData(schema="projects")  # Has to match alembic ini section name


class BaseORM(MappedAsDataclass, DeclarativeBase):
    """Base class for all ORM classes."""

    metadata = metadata_obj


class ProjectORM(BaseORM):
    """A Renku native project."""

    __tablename__ = "projects"
    __table_args__ = (
        Index(
            "projects_unique_namespace_slug",
            "namespace_id",
            "slug_id",
            unique=True,
        ),
    )

    id: Mapped[str] = mapped_column("id", String(26), primary_key=True, default_factory=lambda: str(ULID()), init=False)
    name: Mapped[str] = mapped_column("name", String(99))
    visibility: Mapped[Visibility]
    created_by_id: Mapped[str] = mapped_column("created_by_id", String())
    description: Mapped[Optional[str]] = mapped_column("description", String(500))
    namespace_id: Mapped[Optional[int]] = mapped_column(ForeignKey("groups.namespaces.id"), index=True, nullable=False)
    slug_id: Mapped[int] = mapped_column(ForeignKey("groups.project_slugs"), index=True, nullable=False)
    repositories: Mapped[List["ProjectRepositoryORM"]] = relationship(
        back_populates="project",
        default_factory=list,
        cascade="save-update, merge, delete",
        lazy="selectin",
    )
    creation_date: Mapped[Optional[datetime]] = mapped_column(
        "creation_date", DateTime(timezone=True), default=func.now(), nullable=False
    )

    @classmethod
    def load(cls, project: models.Project):
        """Create ProjectORM from the project model."""
        return cls(
            name=project.name,
            visibility=project.visibility,
            created_by_id=project.created_by.id,
            creation_date=project.creation_date,
            repositories=[ProjectRepositoryORM(url=r) for r in project.repositories],
            description=project.description,
        )

    def dump(self) -> models.Project:
        """Create a project model from the ProjectORM."""
        return models.Project(
            id=self.id,
            name=self.name,
            slug=self.slug,
            visibility=self.visibility,
            created_by=models.Member(id=self.created_by_id),
            creation_date=self.creation_date,
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
    project: Mapped[Optional[ProjectORM]] = relationship(back_populates="repositories", default=None)


class ProjectSlug(BaseORM):
    """Stores all project slugs."""

    __tablename__ = "project_slugs"
    __table_args__ = (
        Index("project_slugs_one_is_latest", "slug", "latest_id", unique=True, postgres_where="latest_id is NULL"),
    )
    id: Mapped[int] = mapped_column(primary_key=True, init=False)
    slug: Mapped[str] = mapped_column(index=True, unique=True, nullable=False)
    latest_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("project_slugs.id", ondelete="CASCADE"), nullable=True, init=False, index=True
    )
    latest: Mapped[Optional["ProjectSlug"]] = relationship(remote_side=[id], lazy="joined", join_depth=1)
