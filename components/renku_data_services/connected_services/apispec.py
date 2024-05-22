# generated by datamodel-codegen:
#   filename:  api.spec.yaml
#   timestamp: 2024-05-22T12:33:27+00:00

from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import ConfigDict, Field, RootModel
from renku_data_services.connected_services.apispec_base import BaseAPISpec


class ProviderKind(Enum):
    gitlab = "gitlab"
    github = "github"


class ConnectionStatus(Enum):
    connected = "connected"
    pending = "pending"


class Error(BaseAPISpec):
    code: int = Field(..., example=1404, gt=0)
    detail: Optional[str] = Field(
        None, example="A more detailed optional message showing what the problem was"
    )
    message: str = Field(..., example="Something went wrong - please try again later")


class ErrorResponse(BaseAPISpec):
    error: Error


class Provider(BaseAPISpec):
    model_config = ConfigDict(
        extra="forbid",
    )
    id: str = Field(
        ...,
        description='ID of a OAuth2 provider, e.g. "gitlab.com".',
        example="some-id",
    )
    kind: ProviderKind
    client_id: str = Field(
        ...,
        description="Client ID or Application ID value. This is provided by\nthe Resource Server when setting up a new OAuth2 Client.\n",
        example="some-client-id",
    )
    client_secret: Optional[str] = Field(
        None,
        description="Client secret provided by the Resource Server when setting\nup a new OAuth2 Client.\n",
        example="some-client-secret",
    )
    display_name: str = Field(..., example="my oauth2 application")
    scope: str = Field(..., example="api")
    url: str = Field(
        ...,
        description='The base URL of the OAuth2 Resource Server, e.g. "https://gitlab.com".\n',
        example="https://example.org",
    )
    use_pkce: bool = Field(
        ...,
        description="Whether or not to use PKCE during authorization flows.\n",
        example=False,
    )


class ProviderPost(BaseAPISpec):
    model_config = ConfigDict(
        extra="forbid",
    )
    id: str = Field(
        ...,
        description='ID of a OAuth2 provider, e.g. "gitlab.com".',
        example="some-id",
    )
    kind: ProviderKind
    client_id: str = Field(
        ...,
        description="Client ID or Application ID value. This is provided by\nthe Resource Server when setting up a new OAuth2 Client.\n",
        example="some-client-id",
    )
    client_secret: Optional[str] = Field(
        None,
        description="Client secret provided by the Resource Server when setting\nup a new OAuth2 Client.\n",
        example="some-client-secret",
    )
    display_name: str = Field(..., example="my oauth2 application")
    scope: str = Field(..., example="api")
    url: str = Field(
        ...,
        description='The base URL of the OAuth2 Resource Server, e.g. "https://gitlab.com".\n',
        example="https://example.org",
    )
    use_pkce: bool = Field(
        ...,
        description="Whether or not to use PKCE during authorization flows.\n",
        example=False,
    )


class ProviderPatch(BaseAPISpec):
    model_config = ConfigDict(
        extra="forbid",
    )
    kind: Optional[ProviderKind] = None
    client_id: Optional[str] = Field(
        None,
        description="Client ID or Application ID value. This is provided by\nthe Resource Server when setting up a new OAuth2 Client.\n",
        example="some-client-id",
    )
    client_secret: Optional[str] = Field(
        None,
        description="Client secret provided by the Resource Server when setting\nup a new OAuth2 Client.\n",
        example="some-client-secret",
    )
    display_name: Optional[str] = Field(None, example="my oauth2 application")
    scope: Optional[str] = Field(None, example="api")
    url: Optional[str] = Field(
        None,
        description='The base URL of the OAuth2 Resource Server, e.g. "https://gitlab.com".\n',
        example="https://example.org",
    )
    use_pkce: Optional[bool] = Field(
        None,
        description="Whether or not to use PKCE during authorization flows.\n",
        example=False,
    )


class Connection(BaseAPISpec):
    model_config = ConfigDict(
        extra="forbid",
    )
    id: str = Field(
        ...,
        description="ULID identifier",
        max_length=26,
        min_length=26,
        pattern="^[A-Z0-9]{26}$",
    )
    provider_id: str = Field(
        ...,
        description='ID of a OAuth2 provider, e.g. "gitlab.com".',
        example="some-id",
    )
    status: ConnectionStatus


class ConnectedAccount(BaseAPISpec):
    model_config = ConfigDict(
        extra="forbid",
    )
    username: str = Field(..., example="some-username")
    web_url: str = Field(
        ...,
        description="A URL which can be opened in a browser, i.e. a web page.",
        example="https://example.org",
    )


class ProviderList(RootModel[List[Provider]]):
    root: List[Provider]


class ConnectionList(RootModel[List[Connection]]):
    root: List[Connection]
