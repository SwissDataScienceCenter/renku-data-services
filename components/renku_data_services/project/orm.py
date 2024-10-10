"""SQLAlchemy's schemas for the projects database."""

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, Identity, Integer, MetaData, String, func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import DeclarativeBase, Mapped, MappedAsDataclass, mapped_column, relationship
from sqlalchemy.schema import ForeignKey
from ulid import ULID

from renku_data_services.authz import models as authz_models
from renku_data_services.base_orm.registry import COMMON_ORM_REGISTRY
from renku_data_services.project import models
from renku_data_services.project.apispec import Visibility
from renku_data_services.utils.sqlalchemy import ULIDType

if TYPE_CHECKING:
    from renku_data_services.namespace.orm import EntitySlugORM


class BaseORM(MappedAsDataclass, DeclarativeBase):
    """Base class for all ORM classes."""

    metadata = MetaData(schema="projects")
    registry = COMMON_ORM_REGISTRY


class ProjectORM(BaseORM):
    """A Renku native project."""

    __tablename__ = "projects"
    id: Mapped[ULID] = mapped_column("id", ULIDType, primary_key=True, default_factory=lambda: str(ULID()), init=False)
    name: Mapped[str] = mapped_column("name", String(99))
    visibility: Mapped[Visibility]
    created_by_id: Mapped[str] = mapped_column("created_by_id", String())
    description: Mapped[str | None] = mapped_column("description", String(500))
    keywords: Mapped[Optional[list[str]]] = mapped_column("keywords", ARRAY(String(99)), nullable=True)
    documentation: Mapped[str | None] = mapped_column("documentation", String(), nullable=True, deferred=True)
    # NOTE: The project slugs table has a foreign key from the projects table, but there is a stored procedure
    # triggered by the deletion of slugs to remove the project used by the slug. See migration 89aa4573cfa9.
    slug: Mapped["EntitySlugORM"] = relationship(
        lazy="joined", init=False, repr=False, viewonly=True, back_populates="project"
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
