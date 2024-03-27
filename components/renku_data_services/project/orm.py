"""SQLAlchemy's schemas for the projects database."""

from datetime import datetime
from typing import List, Optional

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

    id: Mapped[str] = mapped_column("id", String(26), primary_key=True, default_factory=lambda: str(ULID()), init=False)
    name: Mapped[str] = mapped_column("name", String(99))
    slug: Mapped[str] = mapped_column("slug", String(99))
    visibility: Mapped[Visibility]
    created_by_id: Mapped[str] = mapped_column("created_by_id", String())
    description: Mapped[str | None] = mapped_column("description", String(500))
    creation_date: Mapped[datetime | None] = mapped_column(
        "creation_date", DateTime(timezone=True), default=None, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        "updated_at", DateTime(timezone=True), default=None, server_default=func.now(), onupdate=func.now()
    )
    repositories: Mapped[List["ProjectRepositoryORM"]] = relationship(
        back_populates="project",
        default_factory=list,
        cascade="save-update, merge, delete",
        lazy="selectin",
    )

    @classmethod
    def load(cls, project: models.Project):
        """Create ProjectORM from the project model."""
        return cls(
            name=project.name,
            slug=project.slug,
            visibility=project.visibility,
            created_by_id=project.created_by.id,
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
    project: Mapped[Optional[ProjectORM]] = relationship(back_populates="repositories", default=None)
