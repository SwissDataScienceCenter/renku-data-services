# generated by datamodel-codegen:
#   filename:  api.spec.yaml
#   timestamp: 2024-06-13T07:53:08+00:00

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import ConfigDict, EmailStr, Field, RootModel
from renku_data_services.namespace.apispec_base import BaseAPISpec


class GroupRole(Enum):
    owner = "owner"
    editor = "editor"
    viewer = "viewer"


class NamespaceKind(Enum):
    group = "group"
    user = "user"


class NamespaceResponse(BaseAPISpec):
    id: str = Field(
        ...,
        description="ULID identifier",
        max_length=26,
        min_length=26,
        pattern="^[A-Z0-9]{26}$",
    )
    name: Optional[str] = Field(
        None,
        description="Renku group or namespace name",
        example="My Renku Group :)",
        max_length=99,
        min_length=1,
    )
    slug: str = Field(
        ...,
        description="A command-line/url friendly name for a namespace",
        example="a-slug-example",
        max_length=99,
        min_length=1,
        pattern="^(?!.*\\.git$|.*\\.atom$|.*[\\-._][\\-._].*)[a-zA-Z0-9][a-zA-Z0-9\\-_.]*$",
    )
    creation_date: Optional[datetime] = Field(
        None,
        description="The date and time the resource was created (in UTC and ISO-8601 format)",
        example="2023-11-01T17:32:28Z",
    )
    created_by: Optional[str] = Field(
        None,
        description="Member's KeyCloak ID",
        example="123-keycloak-user-id-456",
        min_length=1,
        pattern="^[A-Za-z0-9-]+$",
    )
    namespace_kind: NamespaceKind


class Error(BaseAPISpec):
    code: int = Field(..., example=1404, gt=0)
    detail: Optional[str] = Field(
        None, example="A more detailed optional message showing what the problem was"
    )
    message: str = Field(..., example="Something went wrong - please try again later")


class ErrorResponse(BaseAPISpec):
    error: Error


class GroupResponse(BaseAPISpec):
    id: str = Field(
        ...,
        description="ULID identifier",
        max_length=26,
        min_length=26,
        pattern="^[A-Z0-9]{26}$",
    )
    name: str = Field(
        ...,
        description="Renku group or namespace name",
        example="My Renku Group :)",
        max_length=99,
        min_length=1,
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
        description="Member's KeyCloak ID",
        example="123-keycloak-user-id-456",
        min_length=1,
        pattern="^[A-Za-z0-9-]+$",
    )
    description: Optional[str] = Field(
        None, description="A description for the resource", max_length=500
    )


class GroupPostRequest(BaseAPISpec):
    model_config = ConfigDict(
        extra="forbid",
    )
    name: str = Field(
        ...,
        description="Renku group or namespace name",
        example="My Renku Group :)",
        max_length=99,
        min_length=1,
    )
    slug: str = Field(
        ...,
        description="A command-line/url friendly name for a namespace",
        example="a-slug-example",
        max_length=99,
        min_length=1,
        pattern="^(?!.*\\.git$|.*\\.atom$|.*[\\-._][\\-._].*)[a-zA-Z0-9][a-zA-Z0-9\\-_.]*$",
    )
    description: Optional[str] = Field(
        None, description="A description for the resource", max_length=500
    )


class GroupPatchRequest(BaseAPISpec):
    model_config = ConfigDict(
        extra="forbid",
    )
    name: Optional[str] = Field(
        None,
        description="Renku group or namespace name",
        example="My Renku Group :)",
        max_length=99,
        min_length=1,
    )
    slug: Optional[str] = Field(
        None,
        description="A command-line/url friendly name for a namespace",
        example="a-slug-example",
        max_length=99,
        min_length=1,
        pattern="^(?!.*\\.git$|.*\\.atom$|.*[\\-._][\\-._].*)[a-zA-Z0-9][a-zA-Z0-9\\-_.]*$",
    )
    description: Optional[str] = Field(
        None, description="A description for the resource", max_length=500
    )


class GroupMemberResponse(BaseAPISpec):
    model_config = ConfigDict(
        extra="forbid",
    )
    id: str = Field(
        ...,
        description="Keycloak user ID",
        example="f74a228b-1790-4276-af5f-25c2424e9b0c",
        pattern="^[A-Za-z0-9]{1}[A-Za-z0-9-]+$",
    )
    email: Optional[EmailStr] = Field(
        None, description="User email", example="some-user@gmail.com"
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
    role: GroupRole


class GroupMemberPatchRequest(BaseAPISpec):
    model_config = ConfigDict(
        extra="forbid",
    )
    id: str = Field(
        ...,
        description="Keycloak user ID",
        example="f74a228b-1790-4276-af5f-25c2424e9b0c",
        pattern="^[A-Za-z0-9]{1}[A-Za-z0-9-]+$",
    )
    role: GroupRole


class GroupMemberResponseList(RootModel[List[GroupMemberResponse]]):
    root: List[GroupMemberResponse] = Field(
        ...,
        description="List of members and their access level to the group",
        example=[
            {"id": "some-keycloak-user-id", "role": "owner"},
            {
                "id": "another-keycloak-user-id",
                "role": "member",
                "email": "user@email.com",
                "first_name": "John",
                "last_name": "Doe",
            },
        ],
        min_length=0,
    )


class GroupMemberPatchRequestList(RootModel[List[GroupMemberPatchRequest]]):
    root: List[GroupMemberPatchRequest] = Field(
        ...,
        description="List of members and their access level to the group",
        example=[
            {"id": "some-keycloak-user-id", "role": "owner"},
            {"id": "another-keycloak-user-id", "role": "member"},
        ],
        min_length=0,
    )


class NamespaceResponseList(RootModel[List[NamespaceResponse]]):
    root: List[NamespaceResponse] = Field(..., description="A list of Renku namespaces")


class GroupResponseList(RootModel[List[GroupResponse]]):
    root: List[GroupResponse] = Field(..., description="A list of Renku groups")
