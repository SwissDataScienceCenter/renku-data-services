"""This defines an interface to SOLR."""

import json
import logging
from abc import ABC, abstractmethod
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from enum import IntEnum, StrEnum
from types import TracebackType
from typing import Any, Literal, Optional, Protocol, Self, final
from urllib.parse import urljoin, urlparse, urlunparse

from httpx import AsyncClient, BasicAuth, Response
from pydantic import AliasChoices, BaseModel, Field, field_serializer

from renku_data_services.solr.solr_schema import CoreSchema, FieldName, SchemaCommandList


@dataclass
@final
class SolrUser:
    """User for authenticating at SOLR."""

    username: str
    password: str


@dataclass
@final
class SolrClientConfig:
    """Configuration object for instantiating a client."""

    base_url: str
    core: str
    user: Optional[SolrUser] = None
    timeout: int = 600


class SortDirection(StrEnum):
    """Direction for sorting a field."""

    asc = "asc"
    desc = "desc"


@final
class SolrQuery(BaseModel, frozen=True):
    """A query to solr using the JSON request api.

    See: https://solr.apache.org/guide/solr/latest/query-guide/json-request-api.html
    """

    query: str
    filter: list[str] = Field(default_factory=list)
    limit: int = 50
    offset: int = 0
    fields: list[str | FieldName] = Field(default_factory=list)
    sort: list[tuple[FieldName, SortDirection]] = Field(default_factory=list)
    params: dict[str, str] = Field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return the dict representation of this query."""
        return self.model_dump(exclude_defaults=True)

    def with_sort(self, s: list[tuple[FieldName, SortDirection]]) -> Self:
        """Return a copy of this with an updated sort."""
        return self.model_copy(update={"sort": s})

    @field_serializer("sort", when_used="always")
    def __serialize_sort(self, sort: list[tuple[FieldName, SortDirection]]) -> str:
        return ",".join(list(map(lambda t: f"{t[0]} {t[1].value}", sort)))

    @classmethod
    def query_all_fields(cls, qstr: str) -> "SolrQuery":
        """Create a query with defaults returning all fields of a document."""
        return SolrQuery(query=qstr, fields=["*", "score"])


@final
class ResponseHeader(BaseModel):
    """The responseHeader object as returned by solr."""

    status: int
    query_time: int = Field(
        serialization_alias="QTime", validation_alias=AliasChoices("QTime", "queryTime", "query_time"), default=0
    )
    params: dict[str, str] = Field(default_factory=dict)


@final
class UpsertSuccess(BaseModel):
    """Response for an successful update."""

    header: ResponseHeader


class DocVersion(IntEnum):
    """Possible values for the _version_ field.

    The _version_ field can be used to enable optimistic concurrency control:
    https://solr.apache.org/guide/solr/latest/indexing-guide/partial-document-updates.html#optimistic-concurrency
    """

    not_exists = -1
    exists = 1
    off = 0

    @classmethod
    def exact(cls, n: int) -> int:
        """Return the argument, denoting an exact version."""
        return n


type UpsertResponse = UpsertSuccess | Literal["VersionConflict"]


class SolrDocument(Protocol):
    """The base for a document in SOLR.

    All documents should have an `id` property denoting their primary identity.
    """

    id: str

    def to_dict(self) -> dict[str, Any]:
        """Return a dict representation of this document."""
        ...


class ResponseBody(BaseModel):
    """The body of a search response."""

    num_found: int = Field(serialization_alias="numFound", validation_alias=AliasChoices("numFound", "num_found"))
    start: int
    num_found_exact: bool = Field(
        serialization_alias="numFoundExact", validation_alias=AliasChoices("numFoundExact", "num_found_exact")
    )
    docs: list[dict[str, Any]]


class QueryResponse(BaseModel):
    """The complete response object for running a query.

    Note, solr doesn't set the `responseHeader` for get-by-id requests. Otherwise it will be set.
    """

    responseHeader: ResponseHeader = Field(
        serialization_alias="responseHeader",
        validation_alias=AliasChoices("responseHeader", "response_header"),
        default_factory=lambda: ResponseHeader(status=200),
    )
    response: ResponseBody


class SolrClient(AbstractAsyncContextManager, ABC):
    """A client to SOLR."""

    async def close(self) -> None:
        """Shuts down this client."""

    @abstractmethod
    async def get_raw(self, id: str) -> Response:
        """Get a document by id and return the http response."""
        ...

    @abstractmethod
    async def query_raw(self, query: SolrQuery) -> Response:
        """Query documents and return the http response."""
        ...

    @abstractmethod
    async def get(self, id: str) -> QueryResponse:
        """Get a document by id, returning a `QueryResponse`."""
        ...

    @abstractmethod
    async def query(self, query: SolrQuery) -> QueryResponse:
        """Query documents, returning a `QueryResponse`."""
        ...

    @abstractmethod
    async def modify_schema(self, cmds: SchemaCommandList) -> Response:
        """Updates the schema with the given commands."""
        ...

    @abstractmethod
    async def upsert(self, docs: list[SolrDocument]) -> UpsertResponse:
        """Inserts or updates a document in SOLR."""
        ...

    @abstractmethod
    async def get_schema(self) -> CoreSchema:
        """Return the schema of the core."""
        ...


class DefaultSolrClient(SolrClient):
    """Default implementation of the solr client."""

    delegate: AsyncClient
    config: SolrClientConfig

    def __init__(self, cfg: SolrClientConfig):
        self.config = cfg
        url_parsed = list(urlparse(cfg.base_url))
        url_parsed[2] = urljoin(url_parsed[2], f"/solr/{cfg.core}")
        burl = urlunparse(url_parsed)
        bauth = BasicAuth(username=cfg.user.username, password=cfg.user.password) if cfg.user is not None else None
        self.delegate = AsyncClient(auth=bauth, base_url=burl, timeout=cfg.timeout)

    async def __aenter__(self) -> Self:
        await self.delegate.__aenter__()
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        return await self.delegate.__aexit__(exc_type, exc, tb)

    async def get_raw(self, id: str) -> Response:
        """Query documents and return the http response."""
        return await self.delegate.get("/get", params={"wt": "json", "ids": id})

    async def query_raw(self, query: SolrQuery) -> Response:
        """Query documents and return the http response."""
        return await self.delegate.post("/query", params={"wt": "json"}, json=query.to_dict())

    async def get(self, id: str) -> QueryResponse:
        """Get a document by id, returning a `QueryResponse`."""
        resp = await self.get_raw(id)
        return QueryResponse.model_validate(resp.raise_for_status().json())

    async def query(self, query: SolrQuery) -> QueryResponse:
        """Query documents, returning a `QueryResponse`."""
        resp = await self.query_raw(query)
        return QueryResponse.model_validate(resp.raise_for_status().json())

    async def modify_schema(self, cmds: SchemaCommandList) -> Response:
        """Updates the schema with the given commands."""
        data = cmds.to_json()
        logging.debug(f"modify schema: {data}")
        return await self.delegate.post(
            "/schema",
            params={"commit": "true", "overwrite": "true"},
            content=data.encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )

    async def upsert(self, docs: list[SolrDocument]) -> UpsertResponse:
        """Inserts or updates a document in SOLR.

        The `_version_` property determines wether optimistic locking is used. In this
        case the result is either expected to be successful or a version conflict. All
        other outcomes are raised as an exception.
        """
        j = json.dumps([e.to_dict() for e in docs])
        logging.debug(f"upserting: {j}")
        res = await self.delegate.post(
            "/update",
            params={"commit": "true"},
            content=j.encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        match res.status_code:
            case 200:
                h = ResponseHeader.model_validate(res.json()["responseHeader"])
                return UpsertSuccess(header=h)
            case 409:
                return "VersionConflict"
            case _:
                raise Exception(f"Unexpected return code: {res}")

    async def get_schema(self) -> CoreSchema:
        """Return the current schema."""
        resp = await self.delegate.get("/schema")
        cs = CoreSchema.model_validate(resp.json()["schema"])
        return cs

    async def close(self) -> None:
        """Close this client and free resources."""
        return await self.delegate.aclose()
