# generated by datamodel-codegen:
#   filename:  api.spec.yaml
#   timestamp: 2025-01-13T09:07:25+00:00

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Optional, Union

from pydantic import ConfigDict, Field, RootModel
from renku_data_services.session.apispec_base import BaseAPISpec


class EnvironmentKind(Enum):
    GLOBAL = "GLOBAL"
    CUSTOM = "CUSTOM"


class Error(BaseAPISpec):
    code: int = Field(..., example=1404, gt=0)
    detail: Optional[str] = Field(
        None, example="A more detailed optional message showing what the problem was"
    )
    message: str = Field(..., example="Something went wrong - please try again later")


class ErrorResponse(BaseAPISpec):
    error: Error


class GetEnvironmentParams(BaseAPISpec):
    model_config = ConfigDict(
        extra="forbid",
    )
    include_archived: bool = Field(
        False, description="Whether to return archived environments or not"
    )


class EnvironmentsGetParametersQuery(BaseAPISpec):
    get_environment_params: Optional[GetEnvironmentParams] = None


class Environment(BaseAPISpec):
    id: str = Field(
        ...,
        description="ULID identifier",
        max_length=26,
        min_length=26,
        pattern="^[0-7][0-9A-HJKMNP-TV-Z]{25}$",
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
        description="The date and time the resource was created (in UTC and ISO-8601 format)",
        example="2023-11-01T17:32:28Z",
    )
    description: Optional[str] = Field(
        None, description="A description for the resource", max_length=500
    )
    container_image: str = Field(
        ...,
        description="A container image",
        example="renku/renkulab-py:3.10-0.18.1",
        max_length=500,
        pattern="^[a-z0-9]+((\\.|_|__|-+)[a-z0-9]+)*(\\/[a-z0-9]+((\\.|_|__|-+)[a-z0-9]+)*)*(:[a-zA-Z0-9_][a-zA-Z0-9._-]{0,127}|@sha256:[a-fA-F0-9]{64}){0,1}$",
    )
    default_url: str = Field(
        ...,
        description="The default path to open in a session",
        example="/lab",
        max_length=200,
    )
    uid: int = Field(
        ..., description="The user ID used to run the session", gt=0, le=65535
    )
    gid: int = Field(
        ..., description="The group ID used to run the session", gt=0, le=65535
    )
    working_directory: Optional[str] = Field(
        None,
        description="The location where the session will start, if left unset it will default to the session image working directory.",
        example="/home/jovyan/work",
        min_length=1,
    )
    mount_directory: Optional[str] = Field(
        None,
        description="The location where the persistent storage for the session will be mounted, usually it should be identical to or a parent of the working directory, if left unset will default to the working directory.",
        example="/home/jovyan/work",
        min_length=1,
    )
    port: int = Field(
        ...,
        description="The TCP port (on any container in the session) where user requests will be routed to from the ingress",
        gt=0,
        lt=65400,
    )
    command: Optional[List[str]] = Field(
        None,
        description="The command that will be run i.e. will overwrite the image Dockerfile ENTRYPOINT, equivalent to command in Kubernetes",
        min_length=1,
    )
    args: Optional[List[str]] = Field(
        None,
        description="The arguments that will follow the command, i.e. will overwrite the image Dockerfile CMD, equivalent to args in Kubernetes",
        min_length=1,
    )
    is_archived: Optional[bool] = Field(
        None,
        description="Whether this environment is archived and not for use in new projects or not",
    )


class EnvironmentGetInLauncher(Environment):
    environment_kind: EnvironmentKind


class EnvironmentPost(BaseAPISpec):
    name: str = Field(
        ...,
        description="Renku session name",
        example="My Renku Session :)",
        max_length=99,
        min_length=1,
    )
    description: Optional[str] = Field(
        None, description="A description for the resource", max_length=500
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
    uid: int = Field(
        1000, description="The user ID used to run the session", gt=0, le=65535
    )
    gid: int = Field(
        1000, description="The group ID used to run the session", gt=0, le=65535
    )
    working_directory: Optional[str] = Field(
        None,
        description="The location where the session will start, if left unset it will default to the session image working directory.",
        example="/home/jovyan/work",
        min_length=1,
    )
    mount_directory: Optional[str] = Field(
        None,
        description="The location where the persistent storage for the session will be mounted, usually it should be identical to or a parent of the working directory, if left unset will default to the working directory.",
        example="/home/jovyan/work",
        min_length=1,
    )
    port: int = Field(
        8080,
        description="The TCP port (on any container in the session) where user requests will be routed to from the ingress",
        gt=0,
        lt=65400,
    )
    command: Optional[List[str]] = Field(
        None,
        description="The command that will be run i.e. will overwrite the image Dockerfile ENTRYPOINT, equivalent to command in Kubernetes",
        min_length=1,
    )
    args: Optional[List[str]] = Field(
        None,
        description="The arguments that will follow the command, i.e. will overwrite the image Dockerfile CMD, equivalent to args in Kubernetes",
        min_length=1,
    )
    is_archived: bool = Field(
        False,
        description="Whether this environment is archived and not for use in new projects or not",
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
    description: Optional[str] = Field(
        None, description="A description for the resource", max_length=500
    )
    container_image: Optional[str] = Field(
        None,
        description="A container image",
        example="renku/renkulab-py:3.10-0.18.1",
        max_length=500,
        pattern="^[a-z0-9]+((\\.|_|__|-+)[a-z0-9]+)*(\\/[a-z0-9]+((\\.|_|__|-+)[a-z0-9]+)*)*(:[a-zA-Z0-9_][a-zA-Z0-9._-]{0,127}|@sha256:[a-fA-F0-9]{64}){0,1}$",
    )
    default_url: Optional[str] = Field(
        None,
        description="The default path to open in a session",
        example="/lab",
        max_length=200,
    )
    uid: Optional[int] = Field(
        None, description="The user ID used to run the session", gt=0, le=65535
    )
    gid: Optional[int] = Field(
        None, description="The group ID used to run the session", gt=0, le=65535
    )
    working_directory: Optional[str] = Field(None, example="/home/jovyan/work")
    mount_directory: Optional[str] = Field(None, example="/home/jovyan/work")
    port: Optional[int] = Field(
        None,
        description="The TCP port (on any container in the session) where user requests will be routed to from the ingress",
        gt=0,
        lt=65400,
    )
    command: Optional[List[str]] = Field(
        None,
        description="The command that will be run i.e. will overwrite the image Dockerfile ENTRYPOINT, equivalent to command in Kubernetes",
        min_length=1,
    )
    args: Optional[List[str]] = Field(
        None,
        description="The arguments that will follow the command, i.e. will overwrite the image Dockerfile CMD, equivalent to args in Kubernetes",
        min_length=1,
    )
    is_archived: Optional[bool] = Field(
        None,
        description="Whether this environment is archived and not for use in new projects or not",
    )


class SessionLauncher(BaseAPISpec):
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
        description="Renku session name",
        example="My Renku Session :)",
        max_length=99,
        min_length=1,
    )
    creation_date: datetime = Field(
        ...,
        description="The date and time the resource was created (in UTC and ISO-8601 format)",
        example="2023-11-01T17:32:28Z",
    )
    description: Optional[str] = Field(
        None, description="A description for the resource", max_length=500
    )
    environment: EnvironmentGetInLauncher
    resource_class_id: Optional[int] = Field(
        ..., description="The identifier of a resource class"
    )
    disk_storage: Optional[int] = Field(
        None,
        description="The size of disk storage for the session, in gigabytes",
        example=8,
        ge=1,
    )


class EnvironmentIdOnlyPatch(BaseAPISpec):
    id: Optional[str] = Field(
        None,
        description="Id of the environment to use",
        example="01AN4Z79ZS6XX96588FDX0H099",
        min_length=1,
    )


class EnvironmentIdOnlyPost(BaseAPISpec):
    id: str = Field(
        ...,
        description="Id of the environment to use",
        example="01AN4Z79ZS6XX96588FDX0H099",
        min_length=1,
    )


class EnvironmentList(RootModel[List[Environment]]):
    root: List[Environment] = Field(..., description="A list of session environments")


class EnvironmentPostInLauncher(EnvironmentPost):
    environment_kind: EnvironmentKind


class EnvironmentPatchInLauncher(EnvironmentPatch):
    environment_kind: Optional[EnvironmentKind] = None


class SessionLaunchersList(RootModel[List[SessionLauncher]]):
    root: List[SessionLauncher] = Field(
        ..., description="A list of Renku session launchers", min_length=0
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
        pattern="^[0-7][0-9A-HJKMNP-TV-Z]{25}$",
    )
    description: Optional[str] = Field(
        None, description="A description for the resource", max_length=500
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
    environment: Union[EnvironmentPostInLauncher, EnvironmentIdOnlyPost]


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
    description: Optional[str] = Field(
        None, description="A description for the resource", max_length=500
    )
    resource_class_id: Optional[int] = Field(
        None, description="The identifier of a resource class"
    )
    disk_storage: Optional[int] = Field(None, ge=1)
    environment: Optional[Union[EnvironmentPatchInLauncher, EnvironmentIdOnlyPatch]] = (
        None
    )
