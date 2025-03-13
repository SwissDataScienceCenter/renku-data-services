# generated by datamodel-codegen:
#   filename:  api.spec.yaml
#   timestamp: 2025-03-19T10:21:18+00:00

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Union

from pydantic import ConfigDict, Field, RootModel
from renku_data_services.data_connectors.apispec_base import BaseAPISpec


class Example(BaseAPISpec):
    value: Optional[str] = Field(
        None, description="a potential value for the option (think enum)"
    )
    help: Optional[str] = Field(None, description="help text for the value")
    provider: Optional[str] = Field(
        None,
        description="The provider this value is applicable for. Empty if valid for all providers.",
    )


class Type(Enum):
    int = "int"
    bool = "bool"
    string = "string"
    Time = "Time"
    Duration = "Duration"
    MultiEncoder = "MultiEncoder"
    SizeSuffix = "SizeSuffix"
    SpaceSepList = "SpaceSepList"
    CommaSepList = "CommaSepList"
    Tristate = "Tristate"


class RCloneOption(BaseAPISpec):
    name: Optional[str] = Field(None, description="name of the option")
    help: Optional[str] = Field(None, description="help text for the option")
    provider: Optional[str] = Field(
        None,
        description="The cloud provider the option is for (See 'provider' RCloneOption in the schema for potential values)",
        examples=["AWS"],
    )
    default: Optional[Union[float, str, bool, Dict[str, Any], List]] = Field(
        None, description="default value for the option"
    )
    default_str: Optional[str] = Field(
        None, description="string representation of the default value"
    )
    examples: Optional[List[Example]] = Field(
        None,
        description="These list potential values for this option, like an enum. With `exclusive: true`, only a value from the list is allowed.",
    )
    required: Optional[bool] = Field(
        None, description="whether the option is required or not"
    )
    ispassword: Optional[bool] = Field(
        None, description="whether the field is a password (use **** for display)"
    )
    sensitive: Optional[bool] = Field(
        None,
        description="whether the value is sensitive (not stored in the service). Do not send this in requests to the service.",
    )
    advanced: Optional[bool] = Field(
        None,
        description="whether this is an advanced config option (probably don't show these to users)",
    )
    exclusive: Optional[bool] = Field(
        None, description="if true, only values from 'examples' can be used"
    )
    type: Optional[Type] = Field(
        None,
        description="data type of option value. RClone has more options but they map to the ones listed here.",
    )


class Visibility(Enum):
    private = "private"
    public = "public"


class Keyword(RootModel[str]):
    root: str = Field(
        ...,
        description="A single keyword",
        max_length=99,
        min_length=1,
        pattern="^[A-Za-z0-9\\s\\-_.]*$",
    )


class DataConnectorPermissions(BaseAPISpec):
    write: Optional[bool] = Field(
        None, description="The user can edit the data connector"
    )
    delete: Optional[bool] = Field(
        None, description="The user can delete the data connector"
    )
    change_membership: Optional[bool] = Field(
        None, description="The user can manage data connector members"
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
    code: int = Field(..., examples=[1404], gt=0)
    detail: Optional[str] = Field(
        None, examples=["A more detailed optional message showing what the problem was"]
    )
    message: str = Field(
        ..., examples=["Something went wrong - please try again later"]
    )


class ErrorResponse(BaseAPISpec):
    error: Error


class CloudStorageCore(BaseAPISpec):
    model_config = ConfigDict(
        extra="forbid",
    )
    storage_type: str = Field(
        ...,
        description="same as rclone prefix/ rclone config type. Ignored in requests, but returned in responses for convenience.",
    )
    configuration: Dict[str, Union[int, Optional[str], bool, Dict[str, Any]]]
    source_path: str = Field(
        ...,
        description="the source path to mount, usually starts with bucket/container name",
        examples=["bucket/my/storage/folder/"],
    )
    target_path: str = Field(
        ...,
        description="the target path relative to the working directory where the storage should be mounted",
        examples=["my/project/folder"],
    )
    readonly: bool = Field(
        ..., description="Whether this storage should be mounted readonly or not"
    )
    sensitive_fields: List[RCloneOption]


class CloudStorageCorePost(BaseAPISpec):
    model_config = ConfigDict(
        extra="forbid",
    )
    storage_type: Optional[str] = Field(
        None,
        description="same as rclone prefix/ rclone config type. Ignored in requests, but returned in responses for convenience.",
    )
    configuration: Dict[str, Union[int, Optional[str], bool, Dict[str, Any]]]
    source_path: str = Field(
        ...,
        description="the source path to mount, usually starts with bucket/container name",
        examples=["bucket/my/storage/folder/"],
    )
    target_path: str = Field(
        ...,
        description="the target path relative to the working directory where the storage should be mounted",
        examples=["my/project/folder"],
    )
    readonly: bool = Field(
        True, description="Whether this storage should be mounted readonly or not"
    )


class CloudStorageCorePatch(BaseAPISpec):
    model_config = ConfigDict(
        extra="forbid",
    )
    storage_type: Optional[str] = Field(
        None,
        description="same as rclone prefix/ rclone config type. Ignored in requests, but returned in responses for convenience.",
    )
    configuration: Optional[
        Dict[str, Union[int, Optional[str], bool, Dict[str, Any]]]
    ] = None
    source_path: Optional[str] = Field(
        None,
        description="the source path to mount, usually starts with bucket/container name",
        examples=["bucket/my/storage/folder/"],
    )
    target_path: Optional[str] = Field(
        None,
        description="the target path relative to the working directory where the storage should be mounted",
        examples=["my/project/folder"],
    )
    readonly: Optional[bool] = Field(
        None, description="Whether this storage should be mounted readonly or not"
    )


class CloudStorageUrlV2(BaseAPISpec):
    storage_url: str
    target_path: str = Field(
        ...,
        description="the target path relative to the working directory where the storage should be mounted",
        examples=["my/project/folder"],
    )
    readonly: bool = Field(
        True, description="Whether this storage should be mounted readonly or not"
    )


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
        examples=["2023-11-01T17:32:28Z"],
    )
    created_by: str = Field(
        ...,
        description="Keycloak user ID",
        examples=["f74a228b-1790-4276-af5f-25c2424e9b0c"],
        pattern="^[A-Za-z0-9]{1}[A-Za-z0-9-]+$",
    )


class DataConnectorToProjectLinkPost(BaseAPISpec):
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


class DataConnectorSecret(BaseAPISpec):
    name: str = Field(
        ...,
        description="Name of the credential field",
        examples=["secret_key"],
        max_length=99,
        min_length=1,
    )
    secret_id: str = Field(
        ...,
        description="ULID identifier",
        max_length=26,
        min_length=26,
        pattern="^[0-7][0-9A-HJKMNP-TV-Z]{25}$",
    )


class DataConnectorSecretPatch(BaseAPISpec):
    name: str = Field(
        ...,
        description="Name of the credential field",
        examples=["secret_key"],
        max_length=99,
        min_length=1,
    )
    value: Optional[str] = Field(
        ...,
        description="Secret value that can be any text",
        examples=["My secret value"],
        max_length=5000,
        min_length=1,
    )


class DataConnectorsGetQuery(PaginationRequest):
    namespace: str = Field("", description="A namespace, used as a filter.")


class DataConnectorsGetParametersQuery(BaseAPISpec):
    params: Optional[DataConnectorsGetQuery] = None


class DataConnector(BaseAPISpec):
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
        description="Renku data connector name",
        examples=["My Remote Data :)"],
        max_length=99,
        min_length=1,
    )
    namespace: str = Field(
        ...,
        description="A command-line/url friendly name for a single slug or two slugs separated by /",
        example="user1/project-1",
        max_length=200,
        min_length=1,
        pattern="^(?!.*\\.git$|.*\\.atom$|.*[\\-._][\\-._].*)[a-z0-9][a-z0-9\\-_.]*(?<!\\.git)(?<!\\.atom)(?:/[a-z0-9][a-z0-9\\-_.]*){0,1}$",
    )
    slug: str = Field(
        ...,
        description="A command-line/url friendly name for a namespace",
        examples=["a-slug-example"],
        max_length=99,
        min_length=1,
        pattern="^(?!.*\\.git$|.*\\.atom$|.*[\\-._][\\-._].*)[a-z0-9][a-z0-9\\-_.]*$",
    )
    storage: CloudStorageCore
    creation_date: datetime = Field(
        ...,
        description="The date and time the resource was created (in UTC and ISO-8601 format)",
        examples=["2023-11-01T17:32:28Z"],
    )
    created_by: str = Field(
        ...,
        description="Keycloak user ID",
        examples=["f74a228b-1790-4276-af5f-25c2424e9b0c"],
        pattern="^[A-Za-z0-9]{1}[A-Za-z0-9-]+$",
    )
    visibility: Visibility
    description: Optional[str] = Field(
        None, description="A description for the resource", max_length=500
    )
    etag: str = Field(
        ..., description="Entity Tag", examples=["9EE498F9D565D0C41E511377425F32F3"]
    )
    keywords: Optional[List[Keyword]] = Field(
        None,
        description="Project keywords",
        examples=[["project", "keywords"]],
        min_length=0,
    )


class DataConnectorPost(BaseAPISpec):
    model_config = ConfigDict(
        extra="forbid",
    )
    name: str = Field(
        ...,
        description="Renku data connector name",
        examples=["My Remote Data :)"],
        max_length=99,
        min_length=1,
    )
    namespace: str = Field(
        ...,
        description="A command-line/url friendly name for a single slug or two slugs separated by /",
        example="user1/project-1",
        max_length=200,
        min_length=1,
        pattern="^(?!.*\\.git$|.*\\.atom$|.*[\\-._][\\-._].*)[a-z0-9][a-z0-9\\-_.]*(?<!\\.git)(?<!\\.atom)(?:/[a-z0-9][a-z0-9\\-_.]*){0,1}$",
    )
    slug: Optional[str] = Field(
        None,
        description="A command-line/url friendly name for a namespace",
        examples=["a-slug-example"],
        max_length=99,
        min_length=1,
        pattern="^(?!.*\\.git$|.*\\.atom$|.*[\\-._][\\-._].*)[a-z0-9][a-z0-9\\-_.]*$",
    )
    storage: Union[CloudStorageCorePost, CloudStorageUrlV2]
    visibility: Visibility = Visibility.private
    description: Optional[str] = Field(
        None, description="A description for the resource", max_length=500
    )
    keywords: Optional[List[Keyword]] = Field(
        None,
        description="Project keywords",
        examples=[["project", "keywords"]],
        min_length=0,
    )


class DataConnectorPatch(BaseAPISpec):
    model_config = ConfigDict(
        extra="forbid",
    )
    name: Optional[str] = Field(
        None,
        description="Renku data connector name",
        examples=["My Remote Data :)"],
        max_length=99,
        min_length=1,
    )
    namespace: Optional[str] = Field(
        None,
        description="A command-line/url friendly name for a single slug or two slugs separated by /",
        example="user1/project-1",
        max_length=200,
        min_length=1,
        pattern="^(?!.*\\.git$|.*\\.atom$|.*[\\-._][\\-._].*)[a-z0-9][a-z0-9\\-_.]*(?<!\\.git)(?<!\\.atom)(?:/[a-z0-9][a-z0-9\\-_.]*){0,1}$",
    )
    slug: Optional[str] = Field(
        None,
        description="A command-line/url friendly name for a namespace",
        examples=["a-slug-example"],
        max_length=99,
        min_length=1,
        pattern="^(?!.*\\.git$|.*\\.atom$|.*[\\-._][\\-._].*)[a-z0-9][a-z0-9\\-_.]*$",
    )
    storage: Optional[CloudStorageCorePatch] = None
    visibility: Optional[Visibility] = None
    description: Optional[str] = Field(
        None, description="A description for the resource", max_length=500
    )
    keywords: Optional[List[Keyword]] = Field(
        None,
        description="Project keywords",
        examples=[["project", "keywords"]],
        min_length=0,
    )


class DataConnectorToProjectLinksList(RootModel[List[DataConnectorToProjectLink]]):
    root: List[DataConnectorToProjectLink] = Field(
        ..., description="A list of links from a data connector to a project"
    )


class DataConnectorSecretsList(RootModel[List[DataConnectorSecret]]):
    root: List[DataConnectorSecret] = Field(
        ..., description="A list of data connectors"
    )


class DataConnectorSecretPatchList(RootModel[List[DataConnectorSecretPatch]]):
    root: List[DataConnectorSecretPatch] = Field(
        ..., description="List of secrets to be saved for a data connector"
    )


class DataConnectorsList(RootModel[List[DataConnector]]):
    root: List[DataConnector] = Field(..., description="A list of data connectors")
