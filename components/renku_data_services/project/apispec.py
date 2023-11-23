# generated by datamodel-codegen:
#   filename:  api.spec.yaml
#   timestamp: 2023-11-23T21:33:19+00:00

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import Field, RootModel

from renku_data_services.project.apispec_base import BaseAPISpec


class Visibility(Enum):
    private = "private"
    public = "public"


class Role(Enum):
    member = "member"
    owner = "owner"


class Version(BaseAPISpec):
    version: str


class Error(BaseAPISpec):
    code: int = Field(..., example=1404, gt=0)
    detail: Optional[str] = Field(None, example="A more detailed optional message showing what the problem was")
    message: str = Field(..., example="Something went wrong - please try again later")


class ErrorResponse(BaseAPISpec):
    error: Error


class User(BaseAPISpec):
    id: str = Field(
        ...,
        description="User's KeyCloak ID",
        example="123-keycloak-user-id-456",
        min_length=1,
        pattern="^[A-Za-z0-9-]+$",
    )


class MemberWithRole(BaseAPISpec):
    user: User
    role: Role


class ProjectPost(BaseAPISpec):
    name: str = Field(..., description="Renku project name", example="My Renku Project :)", max_length=99, min_length=1)
    slug: Optional[str] = Field(
        None,
        description="A command-line friendly name for a project",
        example="my-renku-project",
        max_length=99,
        min_length=1,
        pattern="^[a-z0-9]+[a-z0-9._-]*$",
    )
    repositories: Optional[List[str]] = Field(
        None,
        description="A list of repository URLs",
        example=[
            "https://github.com/SwissDataScienceCenter/project-1.git",
            "git@github.com:SwissDataScienceCenter/project-2.git",
        ],
        min_length=0,
    )
    visibility: Visibility = "private"
    description: Optional[str] = Field(None, description="A description for project", max_length=500)


class ProjectPatch(BaseAPISpec):
    name: Optional[str] = Field(
        None, description="Renku project name", example="My Renku Project :)", max_length=99, min_length=1
    )
    slug: Optional[str] = Field(
        None,
        description="A command-line friendly name for a project",
        example="my-renku-project",
        max_length=99,
        min_length=1,
        pattern="^[a-z0-9]+[a-z0-9._-]*$",
    )
    repositories: Optional[List[str]] = Field(
        None,
        description="A list of repository URLs",
        example=[
            "https://github.com/SwissDataScienceCenter/project-1.git",
            "git@github.com:SwissDataScienceCenter/project-2.git",
        ],
        min_length=0,
    )
    visibility: Optional[Visibility] = None
    description: Optional[str] = Field(None, description="A description for project", max_length=500)


class Project(BaseAPISpec):
    id: str = Field(..., description="ULID identifier", max_length=26, min_length=26, pattern="^[A-Z0-9]{26}$")
    name: str = Field(..., description="Renku project name", example="My Renku Project :)", max_length=99, min_length=1)
    slug: str = Field(
        ...,
        description="A command-line friendly name for a project",
        example="my-renku-project",
        max_length=99,
        min_length=1,
        pattern="^[a-z0-9]+[a-z0-9._-]*$",
    )
    creation_date: datetime = Field(
        ...,
        description="The date and time the project was created (time is always in UTC)",
        example="2023-11-01T17:32:28Z",
    )
    created_by: User
    repositories: Optional[List[str]] = Field(
        None,
        description="A list of repository URLs",
        example=[
            "https://github.com/SwissDataScienceCenter/project-1.git",
            "git@github.com:SwissDataScienceCenter/project-2.git",
        ],
        min_length=0,
    )
    visibility: Visibility
    description: Optional[str] = Field(None, description="A description for project", max_length=500)
    members: Optional[List[MemberWithRole]] = Field(
        None, description="List of users and their access level to the project", min_length=0
    )


class ProjectsList(RootModel):
    root: List[Project] = Field(..., description="A list of Renku projects", min_length=0)
