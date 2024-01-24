"""Models for project."""

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

from pydantic import BaseModel

from renku_data_services import errors
from renku_data_services.project.apispec import Role, Visibility


@dataclass(frozen=True, eq=True, kw_only=True)
class Member(BaseModel):
    """Member model."""

    id: str

    @classmethod
    def from_dict(cls, data: dict) -> "Member":
        """Create an instance from a dictionary."""
        return cls(**data)


@dataclass(frozen=True, eq=True, kw_only=True)
class MemberWithRole(BaseModel):
    """Model for project's members."""

    member: Member
    role: Role

    @classmethod
    def from_dict(cls, data: dict) -> "MemberWithRole":
        """Create an instance from a dictionary."""
        member = data.get("member")
        if not member or not isinstance(member, dict) or "id" not in member:
            raise errors.ValidationError(message="'member' not set or doesn't have 'id'")
        if "role" not in data:
            raise errors.ValidationError(message="'role' not set")

        return cls(member=Member.from_dict(member), role=Role(data["role"]))


Repository = str


@dataclass(frozen=True, eq=True, kw_only=True)
class Project(BaseModel):
    """Project model."""

    id: Optional[str]
    name: str
    slug: str
    visibility: Visibility
    created_by: Member
    creation_date: Optional[datetime] = None
    repositories: List[Repository] = field(default_factory=list)
    description: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict) -> "Project":
        """Create the model from a plain dictionary."""
        if "name" not in data:
            raise errors.ValidationError(message="'name' not set")
        if "created_by" not in data:
            raise errors.ValidationError(message="'created_by' not set")
        if not isinstance(data["created_by"], Member):
            raise errors.ValidationError(message="'created_by' must be an instance of 'Member'")

        project_id = data.get("id")
        name = data["name"]
        slug = data.get("slug") or get_slug(name)
        created_by = data["created_by"]
        creation_date = data.get("creation_date") or datetime.now(timezone.utc).replace(microsecond=0)

        return cls(
            id=project_id,
            name=name,
            slug=slug,
            created_by=created_by,
            visibility=data.get("visibility", Visibility.private),
            creation_date=creation_date,
            repositories=[Repository(r) for r in data.get("repositories", [])],
            description=data.get("description"),
        )


def get_slug(name: str, invalid_chars: Optional[List[str]] = None, lowercase: bool = True) -> str:
    """Create a slug from name."""
    invalid_chars = invalid_chars or []
    lower_case = name.lower() if lowercase else name
    no_space = re.sub(r"\s+", "-", lower_case)
    normalized = unicodedata.normalize("NFKD", no_space).encode("ascii", "ignore").decode("utf-8")

    valid_chars_pattern = [r"\w", ".", "_", "-"]
    if len(invalid_chars) > 0:
        valid_chars_pattern = [ch for ch in valid_chars_pattern if ch not in invalid_chars]

    no_invalid_characters = re.sub(f'[^{"".join(valid_chars_pattern)}]', "-", normalized)
    no_duplicates = re.sub(r"([._-])[._-]+", r"\1", no_invalid_characters)
    valid_start = re.sub(r"^[._-]", "", no_duplicates)
    valid_end = re.sub(r"[._-]$", "", valid_start)
    no_dot_git_or_dot_atom_at_end = re.sub(r"(\.atom|\.git)+$", "", valid_end)
    return no_dot_git_or_dot_atom_at_end