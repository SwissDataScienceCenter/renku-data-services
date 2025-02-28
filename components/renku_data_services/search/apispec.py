# generated by datamodel-codegen:
#   filename:  api.spec.yaml
#   timestamp: 2025-03-06T16:14:54+00:00

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Dict, List, Literal, Optional, Union

from pydantic import Field
from renku_data_services.search.apispec_base import BaseAPISpec


class Group(BaseAPISpec):
    id: str
    name: str
    namespace: str
    description: Optional[str] = None
    score: Optional[float] = None
    type: Literal["Group"] = "Group"


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


class Visibility(Enum):
    private = "private"
    public = "public"


class Error(BaseAPISpec):
    code: int = Field(..., example=1404, gt=0)
    detail: Optional[str] = Field(
        None, example="A more detailed optional message showing what the problem was"
    )
    message: str = Field(..., example="Something went wrong - please try again later")


class ErrorResponse(BaseAPISpec):
    error: Error


class FacetData(BaseAPISpec):
    entityType: Dict[str, int]


class Project(BaseAPISpec):
    id: str
    name: str
    slug: str
    namespace: Optional[Union[Group, User]] = Field(
        None,
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
    repositories: Optional[List[str]] = None
    visibility: Visibility
    description: Optional[str] = None
    createdBy: Optional[User] = None
    creationDate: datetime
    keywords: Optional[List[str]] = None
    score: Optional[float] = None
    type: Literal["Project"] = "Project"


class SearchResult(BaseAPISpec):
    items: Optional[List[Union[Group, Project, User]]] = None
    facets: FacetData
    pagingInfo: PageWithTotals


class Reprovisioning(BaseAPISpec):
    id: str = Field(
        ...,
        description="ULID identifier",
        max_length=26,
        min_length=26,
        pattern="^[0-7][0-9A-HJKMNP-TV-Z]{25}$",
    )
    start_date: datetime = Field(
        ...,
        description="The date and time the reprovisioning was started (in UTC and ISO-8601 format)",
        example="2023-11-01T17:32:28Z",
    )


class ReprovisioningStatus(Reprovisioning):
    pass
