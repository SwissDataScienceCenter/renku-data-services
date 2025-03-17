# generated by datamodel-codegen:
#   filename:  api.spec.yaml
#   timestamp: 2025-03-12T11:42:14+00:00

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Optional, Union

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


class ProjectMigrationInfo(BaseAPISpec):
    project_id: str = Field(
        ...,
        description="ULID identifier",
        max_length=26,
        min_length=26,
        pattern="^[0-7][0-9A-HJKMNP-TV-Z]{25}$",
    )
    v1_id: int = Field(..., description="The id of the project in v1")
    launcher_id: Optional[str] = Field(
        None,
        description="ULID identifier",
        max_length=26,
        min_length=26,
        pattern="^[0-7][0-9A-HJKMNP-TV-Z]{25}$",
    )


class ProjectPermissions(BaseAPISpec):
    write: Optional[bool] = Field(None, description="The user can edit the project")
    delete: Optional[bool] = Field(None, description="The user can delete the project")
    change_membership: Optional[bool] = Field(
        None, description="The user can manage project members"
    )


class SessionSecretPatch1(BaseAPISpec):
    secret_slot_id: str = Field(
        ...,
        description="ULID identifier",
        max_length=26,
        min_length=26,
        pattern="^[0-7][0-9A-HJKMNP-TV-Z]{25}$",
    )


class SessionSecretPatchExistingSecret(BaseAPISpec):
    model_config = ConfigDict(
        extra="forbid",
    )
    secret_id: str = Field(
        ...,
        description="ULID identifier",
        max_length=26,
        min_length=26,
        pattern="^[0-7][0-9A-HJKMNP-TV-Z]{25}$",
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


class ProjectsProjectIdCopiesGetParametersQuery(BaseAPISpec):
    writable: bool = False


class MigrationSessionLauncherPost(BaseAPISpec):
    model_config = ConfigDict(
        extra="forbid",
    )
    name: str = Field(
        ...,
        description="Renku session name",
        example="My Renku Session :)",
        max_length=99,
        min_length=1,
    )
    container_image: str = Field(
        ...,
        description="A container image",
        example="renku/renkulab-py:3.10-0.18.1",
        max_length=500,
        pattern="^[a-z0-9]+((\\.|_|__|-+)[a-z0-9]+)*(\\/[a-z0-9]+((\\.|_|__|-+)[a-z0-9]+)*)*(:[a-zA-Z0-9_][a-zA-Z0-9._-]{0,127}|@sha256:[a-fA-F0-9]{64}){0,1}$",
    )
    default_url: str = Field(
        "/lab",
        description="The default path to open in a session",
        example="/lab",
        max_length=200,
    )
    resource_class_id: Optional[int] = Field(
        None, description="The identifier of a resource class"
    )
    disk_storage: Optional[int] = Field(
        None,
        description="The size of disk storage for the session, in gigabytes",
        example=8,
        ge=1,
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


class SessionSecretSlot(BaseAPISpec):
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
    project_id: str = Field(
        ...,
        description="ULID identifier",
        max_length=26,
        min_length=26,
        pattern="^[0-7][0-9A-HJKMNP-TV-Z]{25}$",
    )
    name: str = Field(
        ...,
        description="The name of a secret slot",
        example="API Token",
        max_length=99,
        min_length=1,
    )
    description: Optional[str] = Field(
        None, description="A description for the resource", max_length=500
    )
    filename: str = Field(
        ...,
        description="The filename given to the corresponding secret in the session",
        example="api_token",
        max_length=200,
        min_length=1,
        pattern="^[a-zA-Z0-9_\\-.]+$",
    )
    etag: str = Field(
        ..., description="Entity Tag", example="9EE498F9D565D0C41E511377425F32F3"
    )


class SessionSecretSlotPost(BaseAPISpec):
    model_config = ConfigDict(
        extra="forbid",
    )
    project_id: str = Field(
        ...,
        description="ULID identifier",
        max_length=26,
        min_length=26,
        pattern="^[0-7][0-9A-HJKMNP-TV-Z]{25}$",
    )
    name: Optional[str] = Field(
        None,
        description="The name of a secret slot",
        example="API Token",
        max_length=99,
        min_length=1,
    )
    description: Optional[str] = Field(
        None, description="A description for the resource", max_length=500
    )
    filename: str = Field(
        ...,
        description="The filename given to the corresponding secret in the session",
        example="api_token",
        max_length=200,
        min_length=1,
        pattern="^[a-zA-Z0-9_\\-.]+$",
    )


class SessionSecretSlotPatch(BaseAPISpec):
    model_config = ConfigDict(
        extra="forbid",
    )
    name: Optional[str] = Field(
        None,
        description="The name of a secret slot",
        example="API Token",
        max_length=99,
        min_length=1,
    )
    description: Optional[str] = Field(
        None, description="A description for the resource", max_length=500
    )
    filename: Optional[str] = Field(
        None,
        description="The filename given to the corresponding secret in the session",
        example="api_token",
        max_length=200,
        min_length=1,
        pattern="^[a-zA-Z0-9_\\-.]+$",
    )


class SessionSecret(BaseAPISpec):
    model_config = ConfigDict(
        extra="forbid",
    )
    secret_slot: SessionSecretSlot
    secret_id: str = Field(
        ...,
        description="ULID identifier",
        max_length=26,
        min_length=26,
        pattern="^[0-7][0-9A-HJKMNP-TV-Z]{25}$",
    )


class SessionSecretPatch2(SessionSecretPatchExistingSecret, SessionSecretPatch1):
    pass


class SessionSecretPatchSecretValue(BaseAPISpec):
    model_config = ConfigDict(
        extra="forbid",
    )
    value: Optional[str] = Field(
        None,
        description="Secret value that can be any text",
        example="My secret value",
        max_length=5000,
        min_length=1,
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
    template_id: Optional[str] = Field(
        None,
        description="ULID identifier",
        max_length=26,
        min_length=26,
        pattern="^[0-7][0-9A-HJKMNP-TV-Z]{25}$",
    )
    is_template: bool = Field(
        False, description="Shows if a project is a template or not"
    )
    secrets_mount_directory: str = Field(
        ...,
        description="The location where the secrets will be provided inside sessions, if left unset it will default to `/secrets`.\nRelative locations are supported and will be mounted relative to the session environment's mount directory.\n",
        example="/secrets",
        min_length=1,
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
    secrets_mount_directory: Optional[str] = Field(
        None,
        description="The location where the secrets will be provided inside sessions, if left unset it will default to `/secrets`.\nRelative locations are supported and will be mounted relative to the session environment's mount directory.\n",
        example="/secrets",
        min_length=1,
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
    template_id: Optional[str] = Field(
        None,
        description="template_id is set when copying a project from a template project and it cannot be modified. This field can be either null or an empty string; a null value won't change it while an empty string value will delete it, meaning that the project is unlinked from its template",
        max_length=0,
        min_length=0,
    )
    is_template: Optional[bool] = Field(
        None, description="Shows if a project is a template or not"
    )
    secrets_mount_directory: Optional[str] = Field(None, example="/secrets")


class ProjectMigrationPost(BaseAPISpec):
    model_config = ConfigDict(
        extra="forbid",
    )
    project: ProjectPost
    session_launcher: Optional[MigrationSessionLauncherPost] = None


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


class SessionSecretSlotList(RootModel[List[SessionSecretSlot]]):
    root: List[SessionSecretSlot] = Field(
        ..., description="A list of session secret slots"
    )


class SessionSecretList(RootModel[List[SessionSecret]]):
    root: List[SessionSecret] = Field(
        ..., description="A list of session launcher secrets"
    )


class SessionSecretPatch3(SessionSecretPatchSecretValue, SessionSecretPatch1):
    pass


class ProjectsList(RootModel[List[Project]]):
    root: List[Project] = Field(
        ..., description="A list of Renku projects", min_length=0
    )


class SessionSecretPatchList(
    RootModel[List[Union[SessionSecretPatch2, SessionSecretPatch3]]]
):
    root: List[Union[SessionSecretPatch2, SessionSecretPatch3]]
