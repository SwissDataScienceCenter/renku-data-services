"""Models for project."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Optional, TypeAlias

from renku_data_services import base_models, errors
from renku_data_services.authz.models import Visibility
from renku_data_services.utils.etag import compute_etag_from_timestamp

Repository = str


@dataclass(frozen=True, eq=True, kw_only=True)
class Project:
    """Project model."""

    id: Optional[str]
    name: str
    slug: str
    namespace: str
    visibility: Visibility
    created_by: str
    creation_date: datetime = field(default_factory=lambda: datetime.now(UTC).replace(microsecond=0))
    updated_at: datetime | None = field(default=None)
    repositories: list[Repository] = field(default_factory=list)
    description: Optional[str] = None
    keywords: Optional[list[str]] = None

    @property
    def etag(self) -> str | None:
        """Entity tag value for this project object."""
        if self.updated_at is None:
            return None
        return compute_etag_from_timestamp(self.updated_at)

    @classmethod
    def from_dict(cls, data: dict) -> "Project":
        """Create the model from a plain dictionary."""
        if "name" not in data:
            raise errors.ValidationError(message="'name' not set")
        if "created_by" not in data:
            raise errors.ValidationError(message="'created_by' not set")
        if "member" not in data:
            raise errors.ValidationError(message="'created_by' not set")

        project_id = data.get("id")
        name = data["name"]
        slug = base_models.Slug.from_name(data.get("slug") or name).value
        created_by = data["created_by"]
        creation_date = data.get("creation_date") or datetime.now(UTC).replace(microsecond=0)
        namespace = data["namespace"]

        return cls(
            id=project_id,
            name=name,
            namespace=namespace,
            slug=slug,
            created_by=created_by,
            visibility=data.get("visibility", Visibility.PRIVATE),
            creation_date=creation_date,
            updated_at=data.get("updated_at"),
            repositories=[Repository(r) for r in data.get("repositories", [])],
            description=data.get("description"),
            keywords=data.get("keywords")
        )

ProjectsType: TypeAlias = list[Project]

@dataclass
class ProjectUpdate:
    """Inidicates that a project has been updated and retains and the old and new values."""

    old: Project
    new: Project
