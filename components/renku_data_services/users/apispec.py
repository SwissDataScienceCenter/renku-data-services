# generated by datamodel-codegen:
#   filename:  api.spec.yaml
#   timestamp: 2025-03-19T10:21:03+00:00

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import ConfigDict, Field, RootModel
from renku_data_services.users.apispec_base import BaseAPISpec


class UserSecretKey(BaseAPISpec):
    model_config = ConfigDict(
        extra="forbid",
    )
    secret_key: Optional[str] = Field(None, description="The users secret key")


class Version(BaseAPISpec):
    version: str


class Ulid(RootModel[str]):
    root: str = Field(
        ...,
        description="ULID identifier",
        max_length=26,
        min_length=26,
        pattern="^[0-7][0-9A-HJKMNP-TV-Z]{25}$",
    )


class SecretKind(Enum):
    general = "general"
    storage = "storage"


class ProjectSlug(RootModel[str]):
    root: str = Field(
        ...,
        description="The slug used to identify a project",
        examples=["user/my-project"],
        min_length=3,
        pattern="^[a-zA-Z0-9]+([_.\\-/][a-zA-Z0-9]+)*[_.\\-/]?[a-zA-Z0-9]$",
    )


class AddPinnedProject(BaseAPISpec):
    model_config = ConfigDict(
        extra="forbid",
    )
    project_slug: str = Field(
        ...,
        description="The slug used to identify a project",
        examples=["user/my-project"],
        min_length=3,
        pattern="^[a-zA-Z0-9]+([_.\\-/][a-zA-Z0-9]+)*[_.\\-/]?[a-zA-Z0-9]$",
    )


class Error(BaseAPISpec):
    code: int = Field(..., examples=[1404], gt=0)
    detail: Optional[str] = Field(
        None, examples=["A more detailed optional message showing what the problem was"]
    )
    message: str = Field(
        ..., examples=["Something went wrong - please try again later"]
    )


class ErrorResponse(BaseAPISpec):
    error: Error


class UserParams(BaseAPISpec):
    model_config = ConfigDict(
        extra="forbid",
    )
    exact_email: Optional[str] = Field(
        None, description="Return the user(s) with an exact match on the email provided"
    )


class UsersGetParametersQuery(BaseAPISpec):
    user_params: Optional[UserParams] = None


class UserSecretsParams(BaseAPISpec):
    model_config = ConfigDict(
        extra="forbid",
    )
    kind: SecretKind = Field(
        SecretKind.general, description="Filter results based on secret kind"
    )


class UserSecretsGetParametersQuery(BaseAPISpec):
    user_secrets_params: Optional[UserSecretsParams] = None


class DeletePinnedParams(BaseAPISpec):
    model_config = ConfigDict(
        extra="forbid",
    )
    project_slug: str = ""


class UserPreferencesPinnedProjectsDeleteParametersQuery(BaseAPISpec):
    delete_pinned_params: Optional[DeletePinnedParams] = None


class UserWithId(BaseAPISpec):
    model_config = ConfigDict(
        extra="forbid",
    )
    id: str = Field(
        ...,
        description="Keycloak user ID",
        examples=["f74a228b-1790-4276-af5f-25c2424e9b0c"],
        pattern="^[A-Za-z0-9]{1}[A-Za-z0-9-]+$",
    )
    username: str = Field(
        ...,
        description="Handle of the user",
        examples=["some-username"],
        max_length=99,
        min_length=1,
    )
    email: Optional[str] = Field(
        None, description="User email", examples=["some-user@gmail.com"]
    )
    first_name: Optional[str] = Field(
        None,
        description="First or last name of the user",
        examples=["John"],
        max_length=256,
        min_length=1,
    )
    last_name: Optional[str] = Field(
        None,
        description="First or last name of the user",
        examples=["John"],
        max_length=256,
        min_length=1,
    )


class UsersWithId(RootModel[List[UserWithId]]):
    root: List[UserWithId]


class SelfUserInfo(BaseAPISpec):
    model_config = ConfigDict(
        extra="forbid",
    )
    id: str = Field(
        ...,
        description="Keycloak user ID",
        examples=["f74a228b-1790-4276-af5f-25c2424e9b0c"],
        pattern="^[A-Za-z0-9]{1}[A-Za-z0-9-]+$",
    )
    username: str = Field(
        ...,
        description="Handle of the user",
        examples=["some-username"],
        max_length=99,
        min_length=1,
    )
    email: Optional[str] = Field(
        None, description="User email", examples=["some-user@gmail.com"]
    )
    first_name: Optional[str] = Field(
        None,
        description="First or last name of the user",
        examples=["John"],
        max_length=256,
        min_length=1,
    )
    last_name: Optional[str] = Field(
        None,
        description="First or last name of the user",
        examples=["John"],
        max_length=256,
        min_length=1,
    )
    is_admin: bool = Field(
        False, description="Whether the user is a platform administrator or not"
    )


class SecretWithId(BaseAPISpec):
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
    name: str = Field(
        ...,
        description="The name of a user secret",
        examples=["API Token"],
        max_length=99,
        min_length=1,
    )
    default_filename: str = Field(
        ...,
        description="Filename to give to this secret when mounted in Renku 1.0 sessions\n",
        examples=["Data-S3-Secret_1"],
        max_length=99,
        min_length=1,
        pattern="^[a-zA-Z0-9_\\-.]*$",
    )
    modification_date: datetime = Field(
        ...,
        description="The date and time the secret was created or modified (this is always in UTC)",
        examples=["2023-11-01T17:32:28Z"],
    )
    kind: SecretKind
    session_secret_slot_ids: List[Ulid]
    data_connector_ids: List[Ulid]


class SecretPost(BaseAPISpec):
    model_config = ConfigDict(
        extra="forbid",
    )
    name: str = Field(
        ...,
        description="The name of a user secret",
        examples=["API Token"],
        max_length=99,
        min_length=1,
    )
    default_filename: Optional[str] = Field(
        None,
        description="Filename to give to this secret when mounted in Renku 1.0 sessions\n",
        examples=["Data-S3-Secret_1"],
        max_length=99,
        min_length=1,
        pattern="^[a-zA-Z0-9_\\-.]*$",
    )
    value: str = Field(
        ...,
        description="Secret value that can be any text",
        max_length=5000,
        min_length=1,
    )
    kind: SecretKind = SecretKind.general


class SecretPatch(BaseAPISpec):
    model_config = ConfigDict(
        extra="forbid",
    )
    name: Optional[str] = Field(
        None,
        description="The name of a user secret",
        examples=["API Token"],
        max_length=99,
        min_length=1,
    )
    default_filename: Optional[str] = Field(
        None,
        description="Filename to give to this secret when mounted in Renku 1.0 sessions\n",
        examples=["Data-S3-Secret_1"],
        max_length=99,
        min_length=1,
        pattern="^[a-zA-Z0-9_\\-.]*$",
    )
    value: Optional[str] = Field(
        None,
        description="Secret value that can be any text",
        max_length=5000,
        min_length=1,
    )


class PinnedProjects(BaseAPISpec):
    project_slugs: Optional[List[ProjectSlug]] = None


class SecretsList(RootModel[List[SecretWithId]]):
    root: List[SecretWithId] = Field(..., description="A list of secrets", min_length=0)


class UserPreferences(BaseAPISpec):
    model_config = ConfigDict(
        extra="forbid",
    )
    user_id: str = Field(
        ...,
        description="Keycloak user ID",
        examples=["f74a228b-1790-4276-af5f-25c2424e9b0c"],
        pattern="^[A-Za-z0-9]{1}[A-Za-z0-9-]+$",
    )
    pinned_projects: PinnedProjects
