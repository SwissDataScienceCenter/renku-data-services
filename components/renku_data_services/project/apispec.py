# generated by datamodel-codegen:
#   filename:  api.spec.yaml
#   timestamp: 2023-11-07T02:27:13+00:00

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import AnyUrl, BaseModel, Extra, Field, PositiveInt, constr


class Ulid(BaseModel):
    __root__: constr(regex=r"^[A-Z0-9]{26}$", min_length=26, max_length=26) = Field(..., description="ULID identifier")


class Name(BaseModel):
    __root__: constr(min_length=1, max_length=99) = Field(
        ..., description="Renku project name", example="My Renku Project :)"
    )


class Slug(BaseModel):
    __root__: constr(regex=r"^[a-z0-9]+[a-z0-9._-]*$", min_length=1, max_length=99) = Field(
        ..., description="A command-line friendly name for a project", example="my-renku-project"
    )


class CreationDate(BaseModel):
    __root__: datetime = Field(
        ..., description="The date and time the project was created", example="2023-11-01T17:32:28Z"
    )


class Description(BaseModel):
    __root__: constr(max_length=5000) = Field(..., description="A description for project")


class UserId(BaseModel):
    __root__: constr(regex=r"^[A-Za-z0-9-]+$", min_length=1) = Field(
        ..., description="KeyCloak user ID", example="123-keycloak-user-id-456"
    )


class GitUrl(BaseModel):
    __root__: AnyUrl = Field(..., description="URL of a Git repository")


class Visibility(Enum):
    public = "public"
    private = "private"


class Role(Enum):
    owner = "owner"
    member = "member"
    admin = "admin"


class Version(BaseModel):
    version: str


class Error(BaseModel):
    code: PositiveInt = Field(..., example=1404)
    detail: Optional[str] = Field(None, example="A more detailed optional message showing what the problem was")
    message: str = Field(..., example="Something went wrong - please try again later")


class ErrorResponse(BaseModel):
    error: Error


class User(BaseModel):
    class Config:
        extra = Extra.forbid

    id: UserId


class RepositoriesList(BaseModel):
    __root__: List[GitUrl] = Field(
        ...,
        description="A list of repository URLs",
        example=[
            "https://github.com/SwissDataScienceCenter/project-1.git",
            "git@github.com:SwissDataScienceCenter/project-2.git",
        ],
        min_items=0,
        unique_items=True,
    )


class MemberWithRole(BaseModel):
    class Config:
        extra = Extra.forbid

    user: User
    role: Optional[Role] = "member"


class Project(BaseModel):
    class Config:
        extra = Extra.forbid

    id: Ulid
    name: Name
    slug: Slug
    creation_date: Optional[CreationDate] = None
    created_by: User
    repositories: Optional[RepositoriesList] = None
    visibility: Visibility
    description: Optional[Description] = None


class ProjectPost(BaseModel):
    class Config:
        extra = Extra.forbid

    name: Name
    slug: Optional[Slug] = None
    repositories: Optional[RepositoriesList] = None
    visibility: Optional[Visibility] = "private"
    description: Optional[Description] = None


class ProjectPatch(BaseModel):
    class Config:
        extra = Extra.forbid

    name: Optional[Name] = None
    slug: Optional[Slug] = None
    repositories: Optional[RepositoriesList] = None
    visibility: Optional[Visibility] = "private"
    description: Optional[Description] = None


class MembersWithRoles(BaseModel):
    __root__: List[MemberWithRole] = Field(
        ..., description="List of users and their access level to the project", min_items=0, unique_items=True
    )


class ProjectsList(BaseModel):
    __root__: List[Project] = Field(..., description="A list of Renku projects", min_items=0, unique_items=True)
