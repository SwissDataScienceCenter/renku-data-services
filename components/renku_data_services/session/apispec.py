# generated by datamodel-codegen:
#   filename:  api.spec.yaml
#   timestamp: 2024-03-29T11:09:50+00:00

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import ConfigDict, Field, RootModel
from renku_data_services.session.apispec_base import BaseAPISpec


class EnvironmentKind(Enum):
    global_environment = "global_environment"
    container_image = "container_image"


class Session(BaseAPISpec):
    model_config = ConfigDict(
        extra="allow",
    )
    name: Optional[str] = Field(
        None,
        description="Renku session name",
        example="My Renku Session :)",
        max_length=99,
        min_length=1,
    )
    url: Optional[str] = None


class Error(BaseAPISpec):
    code: int = Field(..., example=1404, gt=0)
    detail: Optional[str] = Field(None, example="A more detailed optional message showing what the problem was")
    message: str = Field(..., example="Something went wrong - please try again later")


class ErrorResponse(BaseAPISpec):
    error: Error


class Environment(BaseAPISpec):
    id: str = Field(
        ...,
        description="ULID identifier",
        max_length=26,
        min_length=26,
        pattern="^[A-Z0-9]{26}$",
    )
    name: str = Field(
        ...,
        description="Renku session name",
        example="My Renku Session :)",
        max_length=99,
        min_length=1,
    )
    creation_date: datetime = Field(
        ...,
        description="The date and time the session was created (time is always in UTC)",
        example="2023-11-01T17:32:28Z",
    )
    description: Optional[str] = Field(None, description="A description for session", max_length=500)
    container_image: str = Field(
        ...,
        description="A container image",
        example="renku/renkulab-py:3.10-0.18.1",
        max_length=500,
    )
    default_url: Optional[str] = Field(
        None,
        description="The default path to open in a session",
        example="/lab",
        max_length=200,
    )


class EnvironmentPost(BaseAPISpec):
    name: str = Field(
        ...,
        description="Renku session name",
        example="My Renku Session :)",
        max_length=99,
        min_length=1,
    )
    description: Optional[str] = Field(None, description="A description for session", max_length=500)
    container_image: str = Field(
        ...,
        description="A container image",
        example="renku/renkulab-py:3.10-0.18.1",
        max_length=500,
    )
    default_url: Optional[str] = Field(
        None,
        description="The default path to open in a session",
        example="/lab",
        max_length=200,
    )


class EnvironmentPatch(BaseAPISpec):
    model_config = ConfigDict(
        extra="forbid",
    )
    name: Optional[str] = Field(
        None,
        description="Renku session name",
        example="My Renku Session :)",
        max_length=99,
        min_length=1,
    )
    description: Optional[str] = Field(None, description="A description for session", max_length=500)
    container_image: Optional[str] = Field(
        None,
        description="A container image",
        example="renku/renkulab-py:3.10-0.18.1",
        max_length=500,
    )
    default_url: Optional[str] = Field(
        None,
        description="The default path to open in a session",
        example="/lab",
        max_length=200,
    )


class SessionLauncher(BaseAPISpec):
    id: str = Field(
        ...,
        description="ULID identifier",
        max_length=26,
        min_length=26,
        pattern="^[A-Z0-9]{26}$",
    )
    project_id: str = Field(
        ...,
        description="ULID identifier",
        max_length=26,
        min_length=26,
        pattern="^[A-Z0-9]{26}$",
    )
    name: str = Field(
        ...,
        description="Renku session name",
        example="My Renku Session :)",
        max_length=99,
        min_length=1,
    )
    creation_date: datetime = Field(
        ...,
        description="The date and time the session was created (time is always in UTC)",
        example="2023-11-01T17:32:28Z",
    )
    description: Optional[str] = Field(None, description="A description for session", max_length=500)
    environment_kind: EnvironmentKind
    environment_id: Optional[str] = Field(
        None,
        description="Id of the environment to use",
        example="01AN4Z79ZS6XX96588FDX0H099",
        min_length=1,
    )
    container_image: Optional[str] = Field(
        None,
        description="A container image",
        example="renku/renkulab-py:3.10-0.18.1",
        max_length=500,
    )
    default_url: Optional[str] = Field(
        None,
        description="The default path to open in a session",
        example="/lab",
        max_length=200,
    )


class SessionLauncherPost(BaseAPISpec):
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
    project_id: str = Field(
        ...,
        description="ULID identifier",
        max_length=26,
        min_length=26,
        pattern="^[A-Z0-9]{26}$",
    )
    description: Optional[str] = Field(None, description="A description for session", max_length=500)
    environment_kind: EnvironmentKind
    environment_id: Optional[str] = Field(
        None,
        description="Id of the environment to use",
        example="01AN4Z79ZS6XX96588FDX0H099",
        min_length=1,
    )
    container_image: Optional[str] = Field(
        None,
        description="A container image",
        example="renku/renkulab-py:3.10-0.18.1",
        max_length=500,
    )
    default_url: Optional[str] = Field(
        None,
        description="The default path to open in a session",
        example="/lab",
        max_length=200,
    )


class SessionLauncherPatch(BaseAPISpec):
    model_config = ConfigDict(
        extra="forbid",
    )
    name: Optional[str] = Field(
        None,
        description="Renku session name",
        example="My Renku Session :)",
        max_length=99,
        min_length=1,
    )
    description: Optional[str] = Field(None, description="A description for session", max_length=500)
    environment_kind: Optional[EnvironmentKind] = None
    environment_id: Optional[str] = Field(
        None,
        description="Id of the environment to use",
        example="01AN4Z79ZS6XX96588FDX0H099",
        min_length=1,
    )
    container_image: Optional[str] = Field(
        None,
        description="A container image",
        example="renku/renkulab-py:3.10-0.18.1",
        max_length=500,
    )
    default_url: Optional[str] = Field(
        None,
        description="The default path to open in a session",
        example="/lab",
        max_length=200,
    )


class SessionStart(BaseAPISpec):
    model_config = ConfigDict(
        extra="allow",
    )
    resource_class_id: Optional[int] = Field(None, description="The identifier of a resource class")


class EnvironmentList(RootModel[list[Environment]]):
    root: list[Environment] = Field(..., description="A list of session environments")


class SessionLaunchersList(RootModel[list[SessionLauncher]]):
    root: list[SessionLauncher] = Field(..., description="A list of Renku session launchers", min_length=0)
