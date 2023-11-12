"""Models for project."""

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel

import renku_data_services.base_models as base_models
from renku_data_services import errors
from renku_data_services.project.apispec import Visibility


@dataclass(frozen=True, eq=True, kw_only=True)
class Project(BaseModel):
    """Project model."""

    id: Optional[str]
    name: str
    slug: str
    visibility: Visibility
    created_by: base_models.User
    creation_date: Optional[datetime] = None
    repositories: Optional[List[str]] = None
    description: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict) -> "Project":
        """Create the model from a plain dictionary."""
        if "name" not in data:
            raise errors.ValidationError(message="'name' not set")

        name = data["name"]
        slug = data.get("slug") or get_slug(name)

        return cls(
            id=data.get("id"),
            name=name,
            slug=slug,
            created_by=data.get("created_by"),  # TODO: This should come from APIUser
            visibility=data.get("visibility", Visibility.private),
            creation_date=data.get("creation_date"),  # TODO: This should be set to the current time
            repositories=data.get("repositories"),
            description=data.get("description"),
        )


def get_slug(name: str, invalid_chars: Optional[List[str]] = None, lowercase: bool = True) -> str:
    """Create a slug from name."""
    invalid_chars = invalid_chars or []
    lower_case = name.lower() if lowercase else name
    no_space = re.sub(r"\s+", "_", lower_case)
    normalized = unicodedata.normalize("NFKD", no_space).encode("ascii", "ignore").decode("utf-8")

    valid_chars_pattern = [r"\w", ".", "_", "-"]
    if len(invalid_chars) > 0:
        valid_chars_pattern = [ch for ch in valid_chars_pattern if ch not in invalid_chars]

    no_invalid_characters = re.sub(f'[^{"".join(valid_chars_pattern)}]', "_", normalized)
    no_duplicates = re.sub(r"([._-])[._-]+", r"\1", no_invalid_characters)
    valid_start = re.sub(r"^[._-]", "", no_duplicates)
    valid_end = re.sub(r"[._-]$", "", valid_start)
    no_dot_git_or_dot_atom_at_end = re.sub(r"(\.atom|\.git)+$", "", valid_end)
    return no_dot_git_or_dot_atom_at_end
