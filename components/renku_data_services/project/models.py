"""Models for project."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Optional

from renku_data_services import base_models, errors
from renku_data_services.authz.models import Visibility

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
    repositories: list[Repository] = field(default_factory=list)
    description: Optional[str] = None

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
            repositories=[Repository(r) for r in data.get("repositories", [])],
            description=data.get("description"),
        )
