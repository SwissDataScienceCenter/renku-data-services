# generated by datamodel-codegen:
#   filename:  api.spec.yaml
#   timestamp: 2025-04-17T09:21:12+00:00

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Dict, List, Literal, Optional, Union

from pydantic import ConfigDict, Field, RootModel
from renku_data_services.search.apispec_base import BaseAPISpec


class PaginationRequest(BaseAPISpec):
    model_config = ConfigDict(
        extra="forbid",
    )
    page: int = Field(1, description="Result's page number starting from 1", ge=1)
    per_page: int = Field(
        20, description="The number of results per page", ge=1, le=100
    )


class Group(BaseAPISpec):
    id: str
    name: str
    namespace: str
    description: Optional[str] = None
    score: Optional[float] = None
    type: Literal["Group"] = "Group"


class MapEntityTypeInt(RootModel[Optional[Dict[str, int]]]):
    root: Optional[Dict[str, int]] = None


class PageDef(BaseAPISpec):
    limit: int
    offset: int


class PageWithTotals(BaseAPISpec):
    page: PageDef
    totalResult: int
    totalPages: int
    prevPage: Optional[int] = None
    nextPage: Optional[int] = None


class User(BaseAPISpec):
    id: str
    namespace: Optional[str] = None
    firstName: Optional[str] = None
    lastName: Optional[str] = None
    score: Optional[float] = None
    type: Literal["User"] = "User"


class UserOrGroup(RootModel[Union[Group, User]]):
    root: Union[Group, User] = Field(
        ...,
        discriminator="type",
        examples=[
            {
                "type": "Group",
                "id": "2CAF4C73F50D4514A041C9EDDB025A36",
                "name": "SDSC",
                "namespace": "SDSC",
                "description": "SDSC group",
                "score": 1.1,
            }
        ],
        title="UserOrGroup",
    )


class Visibility(Enum):
    private = "private"
    public = "public"


class Ulid(RootModel[str]):
    root: str = Field(
        ...,
        description="ULID identifier",
        max_length=26,
        min_length=26,
        pattern="^[0-7][0-9A-HJKMNP-TV-Z]{25}$",
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


class SearchQuery(PaginationRequest):
    q: str = Field("", description="The search query.")


class FacetData(BaseAPISpec):
    entityType: MapEntityTypeInt


class SearchProject(BaseAPISpec):
    id: str
    name: str
    slug: str
    namespace: Optional[UserOrGroup] = None
    repositories: Optional[List[str]] = None
    visibility: Visibility
    description: Optional[str] = None
    createdBy: Optional[User] = None
    creationDate: datetime
    keywords: Optional[List[str]] = None
    score: Optional[float] = None
    type: Literal["Project"] = "Project"


class SearchDataConnector(BaseAPISpec):
    id: str
    storageType: str
    readonly: bool
    name: str
    slug: str
    namespace: Optional[UserOrGroup] = None
    visibility: Visibility
    description: Optional[str] = None
    createdBy: Optional[User] = None
    creationDate: datetime
    keywords: Optional[List[str]] = None
    score: Optional[float] = None
    type: Literal["DataConnector"] = "DataConnector"


class SearchEntity(RootModel[Union[Group, SearchProject, User, SearchDataConnector]]):
    root: Union[Group, SearchProject, User, SearchDataConnector] = Field(
        ..., discriminator="type", title="SearchEntity"
    )


class SearchResult(BaseAPISpec):
    items: Optional[List[SearchEntity]] = None
    facets: FacetData
    pagingInfo: PageWithTotals


class Reprovisioning(BaseAPISpec):
    id: Ulid
    start_date: datetime = Field(
        ...,
        description="The date and time the reprovisioning was started (in UTC and ISO-8601 format)",
        examples=["2023-11-01T17:32:28Z"],
    )


class ReprovisioningStatus(Reprovisioning):
    pass


class SearchQueryGetParametersQuery(BaseAPISpec):
    params: Optional[SearchQuery] = None
