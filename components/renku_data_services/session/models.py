"""Models for Sessions."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Optional

from pydantic import BaseModel

from renku_data_services import errors


@dataclass(frozen=True, eq=True, kw_only=True)
class Member(BaseModel):
    """Member model."""

    id: str

    @classmethod
    def from_dict(cls, data: dict) -> "Member":
        """Create an instance from a dictionary."""
        return cls(**data)


@dataclass(frozen=True, eq=True, kw_only=True)
class Session(BaseModel):
    """Session model."""

    id: Optional[str]
    name: str
    created_by: Member
    creation_date: Optional[datetime] = None
    description: Optional[str] = None
    environment_id: str
    project_id: str

    @classmethod
    def from_dict(cls, data: Dict) -> "Session":
        """Create the model from a plain dictionary."""
        if "name" not in data:
            raise errors.ValidationError(message="'name' not set")
        if "environment_id" not in data:
            raise errors.ValidationError(message="'environment_id' not set")
        if "project_id" not in data:
            raise errors.ValidationError(message="'project_id' not set")
        if "created_by" not in data:
            raise errors.ValidationError(message="'created_by' not set")
        if not isinstance(data["created_by"], Member):
            raise errors.ValidationError(message="'created_by' must be an instance of 'Member'")

        return cls(
            id=data.get("id"),
            name=data["name"],
            created_by=data["created_by"],
            creation_date=data.get("creation_date") or datetime.now(timezone.utc).replace(microsecond=0),
            description=data.get("description"),
            environment_id=data["environment_id"],
            project_id=data["project_id"],
        )
