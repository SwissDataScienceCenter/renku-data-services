# generated by datamodel-codegen:
#   filename:  api.spec.yaml
#   timestamp: 2024-11-14T22:57:27+00:00

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import ConfigDict, Field, RootModel
from renku_data_services.project.apispec_base import BaseAPISpec


class Keyword(RootModel[str]):
    root: str = Field(
        ...,
        description="A single keyword",
        max_length=99,
        min_length=1,
        pattern="^[A-Za-z0-9\\s\\-_.]*$",
    )


class Visibility(Enum):
    private = "private"
    public = "public"


class Role(Enum):
    viewer = "viewer"
    editor = "editor"
    owner = "owner"


class DataConnectorToProjectLink(BaseAPISpec):
    model_config = ConfigDict(
        extra="forbid",
    )
    id: str = Field(
        ...,
        description="ULID identifier",
        max_length=26,
        min_length=26,
        pattern="^[0-7][0-9A-HJKMNP-TV-Z]{25}$",
    )
    data_connector_id: str = Field(
        ...,
        description="ULID identifier",
        max_length=26,
        min_length=26,
        pattern="^[0-7][0-9A-HJKMNP-TV-Z]{25}$",
    )
    project_id: str = Field(
        ...,
        description="ULID identifier",
        max_length=26,
        min_length=26,
        pattern="^[0-7][0-9A-HJKMNP-TV-Z]{25}$",
    )
    creation_date: datetime = Field(
        ...,
        description="The date and time the resource was created (in UTC and ISO-8601 format)",
        example="2023-11-01T17:32:28Z",
    )
    created_by: str = Field(
        ...,
        description="Keycloak user ID",
        example="f74a228b-1790-4276-af5f-25c2424e9b0c",
        pattern="^[A-Za-z0-9]{1}[A-Za-z0-9-]+$",
    )


class ProjectPermissions(BaseAPISpec):
    write: Optional[bool] = Field(None, description="The user can edit the project")
    delete: Optional[bool] = Field(None, description="The user can delete the project")
    change_membership: Optional[bool] = Field(
        None, description="The user can manage project members"
    )


class PaginationRequest(BaseAPISpec):
    model_config = ConfigDict(
        extra="forbid",
    )
    page: int = Field(1, description="Result's page number starting from 1", ge=1)
    per_page: int = Field(
        20, description="The number of results per page", ge=1, le=100
    )


class Error(BaseAPISpec):
    code: int = Field(..., example=1404, gt=0)
    detail: Optional[str] = Field(
        None, example="A more detailed optional message showing what the problem was"
    )
    message: str = Field(..., example="Something went wrong - please try again later")


class ErrorResponse(BaseAPISpec):
    error: Error


class ProjectsProjectIdGetParametersQuery(BaseAPISpec):
    with_documentation: Optional[bool] = Field(
        None, description="Projects with or without possibly extensive documentation?"
    )


class NamespacesNamespaceProjectsSlugGetParametersQuery(BaseAPISpec):
    with_documentation: Optional[bool] = Field(
        None, description="Projects with or without possibly extensive documentation?"
    )


class ProjectMemberPatchRequest(BaseAPISpec):
    model_config = ConfigDict(
        extra="forbid",
    )
    id: str = Field(
        ...,
        description="Keycloak user ID",
        example="f74a228b-1790-4276-af5f-25c2424e9b0c",
        pattern="^[A-Za-z0-9]{1}[A-Za-z0-9-]+$",
    )
    role: Role


class ProjectMemberResponse(BaseAPISpec):
    model_config = ConfigDict(
        extra="forbid",
    )
    id: str = Field(
        ...,
        description="Keycloak user ID",
        example="f74a228b-1790-4276-af5f-25c2424e9b0c",
        pattern="^[A-Za-z0-9]{1}[A-Za-z0-9-]+$",
    )
    namespace: Optional[str] = Field(
        None,
        description="A command-line/url friendly name for a namespace",
        example="a-slug-example",
        max_length=99,
        min_length=1,
        pattern="^(?!.*\\.git$|.*\\.atom$|.*[\\-._][\\-._].*)[a-zA-Z0-9][a-zA-Z0-9\\-_.]*$",
    )
    first_name: Optional[str] = Field(
        None,
        description="First or last name of the user",
        example="John",
        max_length=256,
        min_length=1,
    )
    last_name: Optional[str] = Field(
        None,
        description="First or last name of the user",
        example="John",
        max_length=256,
        min_length=1,
    )
    role: Role


class DataConnectorToProjectLinksList(RootModel[List[DataConnectorToProjectLink]]):
    root: List[DataConnectorToProjectLink] = Field(
        ..., description="A list of links from a data connector to a project"
    )


class ProjectGetQuery(PaginationRequest):
    namespace: str = Field("", description="A namespace, used as a filter.")
    direct_member: bool = Field(
        False,
        description="A flag to filter projects where the user is a direct member.",
    )


class ProjectsGetParametersQuery(BaseAPISpec):
    params: Optional[ProjectGetQuery] = None


class Project(BaseAPISpec):
    id: str = Field(
        ...,
        description="ULID identifier",
        max_length=26,
        min_length=26,
        pattern="^[0-7][0-9A-HJKMNP-TV-Z]{25}$",
    )
    name: str = Field(
        ...,
        description="Renku project name",
        example="My Renku Project :)",
        max_length=99,
        min_length=1,
    )
    namespace: str = Field(
        ...,
        description="A command-line/url friendly name for a namespace",
        example="a-slug-example",
        max_length=99,
        min_length=1,
        pattern="^(?!.*\\.git$|.*\\.atom$|.*[\\-._][\\-._].*)[a-z0-9][a-z0-9\\-_.]*$",
    )
    slug: str = Field(
        ...,
        description="A command-line/url friendly name for a namespace",
        example="a-slug-example",
        max_length=99,
        min_length=1,
        pattern="^(?!.*\\.git$|.*\\.atom$|.*[\\-._][\\-._].*)[a-zA-Z0-9][a-zA-Z0-9\\-_.]*$",
    )
    creation_date: datetime = Field(
        ...,
        description="The date and time the resource was created (in UTC and ISO-8601 format)",
        example="2023-11-01T17:32:28Z",
    )
    created_by: str = Field(
        ...,
        description="Keycloak user ID",
        example="f74a228b-1790-4276-af5f-25c2424e9b0c",
        pattern="^[A-Za-z0-9]{1}[A-Za-z0-9-]+$",
    )
    updated_at: Optional[datetime] = Field(
        None,
        description="The date and time the resource was updated (in UTC and ISO-8601 format)",
        example="2023-11-01T17:32:28Z",
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
    visibility: Visibility
    description: Optional[str] = Field(
        None, description="A description for the resource", max_length=500
    )
    etag: Optional[str] = Field(
        None, description="Entity Tag", example="9EE498F9D565D0C41E511377425F32F3"
    )
    keywords: Optional[List[Keyword]] = Field(
        None,
        description="Project keywords",
        example=["project", "keywords"],
        min_length=0,
    )
    documentation: Optional[str] = Field(
        None,
        description="Renku project documentation",
        example="My Renku Project Documentation :)",
        max_length=5000,
        min_length=0,
    )


class ProjectPost(BaseAPISpec):
    model_config = ConfigDict(
        extra="forbid",
    )
    name: str = Field(
        ...,
        description="Renku project name",
        example="My Renku Project :)",
        max_length=99,
        min_length=1,
    )
    namespace: str = Field(
        ...,
        description="A command-line/url friendly name for a namespace",
        example="a-slug-example",
        max_length=99,
        min_length=1,
        pattern="^(?!.*\\.git$|.*\\.atom$|.*[\\-._][\\-._].*)[a-z0-9][a-z0-9\\-_.]*$",
    )
    slug: Optional[str] = Field(
        None,
        description="A command-line/url friendly name for a namespace",
        example="a-slug-example",
        max_length=99,
        min_length=1,
        pattern="^(?!.*\\.git$|.*\\.atom$|.*[\\-._][\\-._].*)[a-z0-9][a-z0-9\\-_.]*$",
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
    visibility: Visibility = Visibility.private
    description: Optional[str] = Field(
        None, description="A description for the resource", max_length=500
    )
    keywords: Optional[List[Keyword]] = Field(
        None,
        description="Project keywords",
        example=["project", "keywords"],
        min_length=0,
    )
    documentation: Optional[str] = Field(
        None,
        description="Renku project documentation",
        example="My Renku Project Documentation :)",
        max_length=5000,
        min_length=0,
    )


class ProjectPatch(BaseAPISpec):
    model_config = ConfigDict(
        extra="forbid",
    )
    name: Optional[str] = Field(
        None,
        description="Renku project name",
        example="My Renku Project :)",
        max_length=99,
        min_length=1,
    )
    namespace: Optional[str] = Field(
        None,
        description="A command-line/url friendly name for a namespace",
        example="a-slug-example",
        max_length=99,
        min_length=1,
        pattern="^(?!.*\\.git$|.*\\.atom$|.*[\\-._][\\-._].*)[a-z0-9][a-z0-9\\-_.]*$",
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
    description: Optional[str] = Field(
        None, description="A description for the resource", max_length=500
    )
    keywords: Optional[List[Keyword]] = Field(
        None,
        description="Project keywords",
        example=["project", "keywords"],
        min_length=0,
    )
    documentation: Optional[str] = Field(
        None,
        description="Renku project documentation",
        example="My Renku Project Documentation :)",
        max_length=5000,
        min_length=0,
    )


class ProjectMemberListPatchRequest(RootModel[List[ProjectMemberPatchRequest]]):
    root: List[ProjectMemberPatchRequest] = Field(
        ...,
        description="List of members and their access level to the project",
        example=[
            {"id": "some-keycloak-user-id", "role": "owner"},
            {"id": "another-keycloak-user-id", "role": "viewer"},
        ],
        min_length=0,
    )


class ProjectMemberListResponse(RootModel[List[ProjectMemberResponse]]):
    root: List[ProjectMemberResponse] = Field(
        ...,
        description="List of members with full info and their access level to the project",
        min_length=0,
    )


class ProjectsList(RootModel[List[Project]]):
    root: List[Project] = Field(
        ..., description="A list of Renku projects", min_length=0
    )
