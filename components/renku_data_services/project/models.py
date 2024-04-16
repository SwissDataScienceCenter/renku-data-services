"""Models for project."""

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, Field
from renku_data_services import base_models, errors
from renku_data_services.project.apispec import Role, Visibility
from renku_data_services.utils.etag import compute_etag_from_timestamp


@dataclass(frozen=True, eq=True, kw_only=True)
class MemberWithRole(BaseModel):
    """Model for project's members."""

    member: str  # The keycloakID of the user
    role: Role

    @classmethod
    def from_dict(cls, data: dict) -> "MemberWithRole":
        """Create an instance from a dictionary."""
        if "member" not in data:
            raise errors.ValidationError(message="'member' not set")
        if "role" not in data:
            raise errors.ValidationError(message="'role' not set")

        return cls(member=data["member"], role=Role(data["role"]))


Repository = str


@dataclass(frozen=True, eq=True, kw_only=True)
class Project(BaseModel):
    """Project model."""

    id: Optional[str]
    name: str
    slug: str
    namespace: str
    visibility: Visibility
    created_by: Member
    creation_date: datetime | None = Field(default=None)
    updated_at: datetime | None = Field(default=None)
    repositories: List[Repository] = Field(default_factory=list)
    description: Optional[str] = None

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
        namespace = data["namespace"]

        return cls(
            id=project_id,
            name=name,
            namespace=namespace,
            slug=slug,
            visibility=data.get("visibility", Visibility.private),
            created_by=created_by,
            creation_date=data.get("creation_date"),
            updated_at=data.get("updated_at"),
            repositories=[Repository(r) for r in data.get("repositories", [])],
            description=data.get("description"),
        )
