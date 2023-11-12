"""SQLAlchemy's schemas for the projects database."""

from datetime import datetime
from typing import List

from sqlalchemy import ARRAY, DateTime, MetaData, String
from sqlalchemy.orm import DeclarativeBase, Mapped, MappedAsDataclass, mapped_column
from ulid import ULID

from renku_data_services.project import models
from renku_data_services.project.apispec import Visibility

metadata_obj = MetaData(schema="project")  # Has to match alembic ini section name


class BaseORM(MappedAsDataclass, DeclarativeBase):
    """Base class for all ORM classes."""

    metadata = metadata_obj


class ProjectORM(BaseORM):
    """A Renku native project."""

    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(
        "project_id", String(26), primary_key=True, default_factory=lambda: str(ULID()), init=False
    )

    name: Mapped[str] = mapped_column("name", String(99))

    slug: Mapped[str] = mapped_column("slug", String(99))

    visibility: Mapped[Visibility]

    created_by: Mapped[str] = mapped_column("created_by", String(99))

    creation_date: Mapped[datetime] = mapped_column("creation_date", DateTime(timezone=True))

    repositories: Mapped[List[str]] = mapped_column("repositories", ARRAY(String, dimensions=2))

    description: Mapped[str] = mapped_column("description", String(5000))

    @classmethod
    def load(cls, project: models.Project):
        """Create ProjectORM from the project model."""
        return cls(
            id=project.id,
            name=project.name,
            slug=project.slug,
            visibility=project.visibility,
            created_by=project.created_by,
            creation_date=project.creation_date,
            repositories=project.repositories,
            description=project.description,
        )

    def dump(self):
        """Create a project model from the ProjectORM."""
        return models.Project(
            id=self.id,
            name=self.name,
            slug=self.slug,
            visibility=self.visibility,
            created_by=self.created_by,
            creation_date=self.creation_date,
            repositories=self.repositories,
            description=self.description,
        )
