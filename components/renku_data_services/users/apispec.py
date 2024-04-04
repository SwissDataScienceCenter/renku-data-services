# generated by datamodel-codegen:
#   filename:  api.spec.yaml
#   timestamp: 2024-03-26T12:44:52+00:00

from __future__ import annotations

from typing import List, Optional

from pydantic import ConfigDict, EmailStr, Field, RootModel
from renku_data_services.users.apispec_base import BaseAPISpec


class Version(BaseAPISpec):
    version: str


class Error(BaseAPISpec):
    code: int = Field(..., example=1404, gt=0)
    detail: Optional[str] = Field(
        None, example="A more detailed optional message showing what the problem was"
    )
    message: str = Field(..., example="Something went wrong - please try again later")


class ErrorResponse(BaseAPISpec):
    error: Error


class UserWithId(BaseAPISpec):
    model_config = ConfigDict(
        extra="forbid",
    )
    id: str = Field(
        ...,
        description="Keycloak user ID",
        example="f74a228b-1790-4276-af5f-25c2424e9b0c",
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


class UsersWithId(RootModel[List[UserWithId]]):
    root: List[UserWithId]
