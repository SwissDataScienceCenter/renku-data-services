"""Models for Sessions."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Optional

from pydantic import BaseModel

from renku_data_services import errors
from renku_data_services.project.models import Project
from renku_data_services.session.apispec import EnvironmentKind


@dataclass(frozen=True, eq=True, kw_only=True)
class Member(BaseModel):
    """Member model."""

    id: str

    @classmethod
    def from_dict(cls, data: dict) -> "Member":
        """Create an instance from a dictionary."""
        return cls(**data)


@dataclass(frozen=True, eq=True, kw_only=True)
class SessionEnvironment(BaseModel):
    """Session environment model."""

    id: Optional[str]
    name: str
    created_by: Member
    container_image: str
    creation_date: Optional[datetime] = None
    description: Optional[str] = None

    # @classmethod
    # def from_dict(cls, data: Dict) -> "SessionEnvironment":
    #     """Create the model from a plain dictionary."""
    #     if "name" not in data:
    #         raise errors.ValidationError(message="'name' not set")
    #     if "created_by" not in data:
    #         raise errors.ValidationError(message="'created_by' not set")
    #     if not isinstance(data["created_by"], Member):
    #         raise errors.ValidationError(message="'created_by' must be an instance of 'Member'")
    #     if "container_image" not in data:
    #         raise errors.ValidationError(message="'container_image' not set")

    #     return cls(
    #         id=data.get("id"),
    #         name=data["name"],
    #         created_by=data["created_by"],
    #         creation_date=data.get("creation_date") or datetime.now(timezone.utc).replace(microsecond=0),
    #         description=data.get("description"),
    #         container_image=data["container_image"],
    #     )


@dataclass(frozen=True, eq=True, kw_only=True)
class SessionLauncher(BaseModel):
    """Session launcher model."""

    id: Optional[str]
    project: Project
    name: str
    created_by: Member
    creation_date: Optional[datetime] = None
    description: Optional[str] = None
    environment_kind: EnvironmentKind
    environment: Optional[SessionEnvironment] = None
    container_image: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict) -> "SessionLauncher":
        """Create the model from a plain dictionary."""
        if "project" not in data:
            raise errors.ValidationError(message="'project' not set")
        if not isinstance(data["project"], Project):
            raise errors.ValidationError(message="'created_by' must be an instance of 'Member'")
        if "name" not in data:
            raise errors.ValidationError(message="'name' not set")
        if "created_by" not in data:
            raise errors.ValidationError(message="'created_by' not set")
        if not isinstance(data["created_by"], Member):
            raise errors.ValidationError(message="'created_by' must be an instance of 'Member'")
        if "environment_kind" not in data:
            raise errors.ValidationError(message="'environment_kind' not set")
        if not isinstance(data["environment_kind"], EnvironmentKind):
            raise errors.ValidationError(message="'environment_kind' must be an instance of 'EnvironmentKind'")

        if data["environment_kind"] == EnvironmentKind.global_environment and "environment" not in data:
            raise errors.ValidationError(message="'environment' not set when environment_kind=global_environment")
        if data["environment_kind"] == EnvironmentKind.global_environment and not isinstance(
            data["environment"], SessionEnvironment
        ):
            raise errors.ValidationError(message="'environment'  must be an instance of 'SessionEnvironment'")

        if data["environment_kind"] == EnvironmentKind.container_image and "container_image" not in data:
            raise errors.ValidationError(message="'container_image' not set when environment_kind=container_image")

        return cls(
            id=data.get("id"),
            project=data["project"],
            name=data["name"],
            created_by=data["created_by"],
            creation_date=data.get("creation_date") or datetime.now(timezone.utc).replace(microsecond=0),
            description=data.get("description"),
            environment_kind=data["environment_kind"],
            environment=data.get("environment"),
            container_image=data.get("container_image"),
        )


# @dataclass(frozen=True, eq=True, kw_only=True)
# class Session(BaseModel):
#     """Session model."""

#     id: Optional[str]
#     name: str
#     created_by: Member
#     creation_date: Optional[datetime] = None
#     description: Optional[str] = None
#     environment_id: str
#     project_id: str

#     @classmethod
#     def from_dict(cls, data: Dict) -> "Session":
#         """Create the model from a plain dictionary."""
#         if "name" not in data:
#             raise errors.ValidationError(message="'name' not set")
#         if "environment_id" not in data:
#             raise errors.ValidationError(message="'environment_id' not set")
#         if "project_id" not in data:
#             raise errors.ValidationError(message="'project_id' not set")
#         if "created_by" not in data:
#             raise errors.ValidationError(message="'created_by' not set")
#         if not isinstance(data["created_by"], Member):
#             raise errors.ValidationError(message="'created_by' must be an instance of 'Member'")

#         return cls(
#             id=data.get("id"),
#             name=data["name"],
#             created_by=data["created_by"],
#             creation_date=data.get("creation_date") or datetime.now(timezone.utc).replace(microsecond=0),
#             description=data.get("description"),
#             environment_id=data["environment_id"],
#             project_id=data["project_id"],
#         )
