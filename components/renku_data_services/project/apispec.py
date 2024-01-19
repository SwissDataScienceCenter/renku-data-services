# generated by datamodel-codegen:
#   filename:  api.spec.yaml
#   timestamp: 2024-01-19T00:27:33+00:00

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import ConfigDict, EmailStr, Field, RootModel

from renku_data_services.project.apispec_base import BaseAPISpec


class Visibility(Enum):
    private = "private"
    public = "public"


class Role(Enum):
    member = "member"
    owner = "owner"


class Error(BaseAPISpec):
    code: int = Field(..., example=1404, gt=0)
    detail: Optional[str] = Field(None, example="A more detailed optional message showing what the problem was")
    message: str = Field(..., example="Something went wrong - please try again later")


class ErrorResponse(BaseAPISpec):
    error: Error


class Member(BaseAPISpec):
    model_config = ConfigDict(
        extra="forbid",
    )
    id: str = Field(
        ...,
        description="Member's KeyCloak ID",
        example="123-keycloak-user-id-456",
        min_length=1,
        pattern="^[A-Za-z0-9-]+$",
    )


class MemberWithRole(BaseAPISpec):
    model_config = ConfigDict(
        extra="forbid",
    )
    member: Member
    role: Role


class UserWithId(BaseAPISpec):
    model_config = ConfigDict(
        extra="forbid",
    )
    id: str = Field(..., description="Keycloak user ID", example="f74a228b-1790-4276-af5f-25c2424e9b0c")
    email: Optional[EmailStr] = Field(None, description="User email", example="some-user@gmail.com")
    first_name: Optional[str] = Field(
        None, description="First or last name of the user", example="John", max_length=256, min_length=1
    )
    last_name: Optional[str] = Field(
        None, description="First or last name of the user", example="John", max_length=256, min_length=1
    )


class Project(BaseAPISpec):
    id: str = Field(..., description="ULID identifier", max_length=26, min_length=26, pattern="^[A-Z0-9]{26}$")
    name: str = Field(..., description="Renku project name", example="My Renku Project :)", max_length=99, min_length=1)
    slug: Optional[str] = Field(
        None,
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
    created_by: Member
    repositories: Optional[List[str]] = Field(
        None,
        description="A list of repositories",
        example=[
            "https://github.com/SwissDataScienceCenter/project-1.git",
            "git@github.com:SwissDataScienceCenter/project-2.git",
        ],
        min_length=0,
    )
    visibility: Visibility
    description: Optional[str] = Field(None, description="A description for project", max_length=500)


class ProjectPost(BaseAPISpec):
    model_config = ConfigDict(
        extra="forbid",
    )
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
        description="A list of repositories",
        example=[
            "https://github.com/SwissDataScienceCenter/project-1.git",
            "git@github.com:SwissDataScienceCenter/project-2.git",
        ],
        min_length=0,
    )
    visibility: Visibility = "private"
    description: Optional[str] = Field(None, description="A description for project", max_length=500)


class ProjectPatch(BaseAPISpec):
    model_config = ConfigDict(
        extra="forbid",
    )
    name: Optional[str] = Field(
        None, description="Renku project name", example="My Renku Project :)", max_length=99, min_length=1
    )
    repositories: Optional[List[str]] = Field(
        None,
        description="A list of repositories",
        example=[
            "https://github.com/SwissDataScienceCenter/project-1.git",
            "git@github.com:SwissDataScienceCenter/project-2.git",
        ],
        min_length=0,
    )
    visibility: Optional[Visibility] = None
    description: Optional[str] = Field(None, description="A description for project", max_length=500)


class MembersWithRoles(RootModel[List[MemberWithRole]]):
    root: List[MemberWithRole] = Field(
        ...,
        description="List of members and their access level to the project",
        example=[
            {"id": "some-keycloak-user-id", "role": "owner"},
            {"id": "another-keycloak-user-id", "role": "member"},
        ],
        min_length=0,
    )


class FullUserWithRole(BaseAPISpec):
    model_config = ConfigDict(
        extra="forbid",
    )
    member: UserWithId
    role: Role


class ProjectsList(RootModel[List[Project]]):
    root: List[Project] = Field(..., description="A list of Renku projects", min_length=0)


class FullUsersWithRoles(RootModel[List[FullUserWithRole]]):
    root: List[FullUserWithRole] = Field(
        ..., description="List of members with full info and their access level to the project", min_length=0
    )
