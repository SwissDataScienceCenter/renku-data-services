"""This defines an interface to SOLR."""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from enum import StrEnum
from types import TracebackType
from typing import Any, Literal, NewType, Optional, Protocol, Self, final
from urllib.parse import urljoin, urlparse, urlunparse

from httpx import AsyncClient, BasicAuth, ConnectError, Response
from pydantic import (
    AliasChoices,
    BaseModel,
    Field,
    ModelWrapValidatorHandler,
    ValidationError,
    field_serializer,
    model_serializer,
    model_validator,
)

from renku_data_services.app_config import logging
from renku_data_services.errors.errors import BaseError
from renku_data_services.solr.solr_schema import CoreSchema, FieldName, SchemaCommandList

logger = logging.getLogger(__name__)


@dataclass
@final
class SolrUser:
    """User for authenticating at SOLR."""

    username: str
    password: str = field(repr=False)

    def __str__(self) -> str:
        pstr = "***" if self.password != "" else ""  # nosec
        return f"(user={self.username}, password={pstr})"


@dataclass
@final
class SolrClientConfig:
    """Configuration object for instantiating a client."""

    base_url: str
    core: str
    user: Optional[SolrUser] = None
    timeout: int = 600
    configset: str = "_default"

    @classmethod
    def from_env(cls) -> SolrClientConfig:
        """Create a configuration from environment variables."""
        url = os.environ["SOLR_URL"]
        core = os.environ.get("SOLR_CORE", "renku-search")
        username = os.environ.get("SOLR_USER")
        password = os.environ.get("SOLR_PASSWORD")

        tstr = os.environ.get("SOLR_REQUEST_TIMEOUT", "600")
        try:
            timeout = int(tstr) if tstr is not None else 600
        except ValueError:
            logger.warning(f"SOLR_REQUEST_TIMEOUT is not an integer: {tstr}")
            timeout = 600

        user = SolrUser(username=username, password=str(password)) if username is not None else None
        return cls(url, core, user, timeout)

    def __str__(self) -> str:
        return (
            f"SolrClientConfig(base_url={self.base_url}, core={self.core}, user={self.user}, timeout={self.timeout}"
            f", configset={self.configset})"
        )


class SolrClientException(BaseError, ABC):
    """Base exception for solr client."""

    def __init__(self, message: str, code: int = 1500, status_code: int = 500) -> None:
        super().__init__(message=message, code=code, status_code=status_code)


class SortDirection(StrEnum):
    """Direction for sorting a field."""

    asc = "asc"
    desc = "desc"


@final
class SubQuery(BaseModel, frozen=True):
    """Represents a solr sub query."""

    query: str
    filter: str
    limit: int
    offset: int = 0
    fields: list[str | FieldName] = Field(default_factory=list)
    sort: list[tuple[FieldName, SortDirection]] = Field(default_factory=list)

    def with_sort(self, s: list[tuple[FieldName, SortDirection]]) -> Self:
        """Return a copy with a new sort definition."""
        return self.model_copy(update={"sort": s})

    def with_fields(self, fn: FieldName, *args: FieldName) -> Self:
        """Return a copy with a new field list."""
        fs = [fn] + list(args)
        return self.model_copy(update={"fields": fs})

    def with_all_fields(self) -> Self:
        """Return a copy with fields set to ['*']."""
        return self.model_copy(update={"fields": ["*"]})

    def with_filter(self, q: str) -> Self:
        """Return a copy with a new filter query."""
        return self.model_copy(update={"filter": q})

    def with_query(self, q: str) -> Self:
        """Return a copy with a new query."""
        return self.model_copy(update={"query": q})

    def to_params(self, field: FieldName) -> dict[str, str]:
        """Return a dictionary intended to be added to the main query params."""

        def key(s: str) -> str:
            return f"{field}.{s}"

        result = {key("q"): self.query}
        if self.filter != "":
            result.update({key("fq"): self.filter})

        if self.limit > 0:
            result.update({key("limit"): str(self.limit)})

        if self.offset > 0:
            result.update({key("offset"): str(self.offset)})

        if self.fields != []:
            result.update({key("fl"): ",".join(self.fields)})

        if self.sort != []:
            solr_sort = ",".join(list(map(lambda t: f"{t[0]} {t[1].value}", self.sort)))
            result.update({key("sort"): solr_sort})

        return result


@final
class FacetAlgorithm(StrEnum):
    """Available facet algorithms for solr."""

    doc_values = "dv"
    un_inverted_field = "uif"
    doc_values_hash = "dvhash"
    enum = "enum"
    stream = "stream"
    smart = "smart"


@final
class FacetRange(BaseModel, frozen=True):
    """A range definition used within the FacetRange."""

    start: int | Literal["*"] = Field(serialization_alias="from", validation_alias=AliasChoices("from", "start"))
    to: int | Literal["*"]
    inclusive_from: bool = True
    inclusive_to: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Return the dict of this object."""
        return self.model_dump(by_alias=True)


@final
class FacetTerms(BaseModel, frozen=True):
    """The terms facet request.

    See: https://solr.apache.org/guide/solr/latest/query-guide/json-facet-api.html#terms-facet
    """

    name: FieldName
    field: FieldName
    limit: int | None = None
    min_count: int | None = Field(
        serialization_alias="mincount", validation_alias=AliasChoices("mincount", "min_count"), default=None
    )
    method: FacetAlgorithm | None = None
    missing: bool = False
    num_buckets: bool = Field(
        serialization_alias="numBuckets", validation_alias=AliasChoices("numBuckets", "num_buckets"), default=False
    )
    all_buckets: bool = Field(
        serialization_alias="allBuckets", validation_alias=AliasChoices("allBuckets", "all_buckets"), default=False
    )

    def to_dict(self) -> dict[str, Any]:
        """Return the dict representation of this object."""
        result = self.model_dump(by_alias=True, exclude_none=True)
        result.update({"type": "terms"})
        result.pop("name")
        return {f"{self.name}": result}


@final
class FacetArbitraryRange(BaseModel, frozen=True):
    """The range facet.

    See: https://solr.apache.org/guide/solr/latest/query-guide/json-facet-api.html#range-facet
    """

    name: FieldName
    field: FieldName
    ranges: list[FacetRange]

    def to_dict(self) -> dict[str, Any]:
        """Return the dict of this object."""
        result = self.model_dump(by_alias=True, exclude_defaults=True)
        result.update({"type": "range"})
        result.pop("name")
        return {f"{self.name}": result}


@final
class SolrFacets(BaseModel, frozen=True):
    """A facet query part consisting of multiple facet requests."""

    facets: list[FacetTerms | FacetArbitraryRange]

    @model_serializer()
    def to_dict(self) -> dict[str, Any]:
        """Return the dict representation of this object."""
        result = {}
        [result := result | x.to_dict() for x in self.facets]
        return result

    def with_facet(self, f: FacetTerms | FacetArbitraryRange) -> SolrFacets:
        """Return a copy with the given facet added."""
        return SolrFacets(facets=self.facets + [f])

    @classmethod
    def of(cls, *args: FacetTerms | FacetArbitraryRange) -> SolrFacets:
        """Contsructor accepting varags."""
        return SolrFacets(facets=list(args))

    @classmethod
    def empty(cls) -> SolrFacets:
        """Return an empty facets request."""
        return SolrFacets(facets=[])


@final
class FacetCount(BaseModel, frozen=True):
    """A facet count consists of the field and its determined count."""

    field: FieldName = Field(serialization_alias="val", validation_alias=AliasChoices("val", "field"))
    count: int

    def to_dict(self) -> dict[str, Any]:
        """Return the dict representation of this object."""
        return self.model_dump(by_alias=True)


@final
class FacetBuckets(BaseModel, frozen=True):
    """A list of bucket counts as part of a facet response."""

    buckets: list[FacetCount]

    def to_dict(self) -> dict[str, Any]:
        """Return the dict representation of this object as returned by solr."""
        return self.model_dump(by_alias=True)

    def to_simple_dict(self) -> dict[str, int]:
        """Return the counts as a simple field-count dict."""
        els = [{x.field: x.count} for x in self.buckets]
        result = {}
        [result := result | x for x in els]
        return result

    @classmethod
    def of(cls, *args: FacetCount) -> Self:
        """Constructor for varargs."""
        return FacetBuckets(buckets=list(args))

    @classmethod
    def empty(cls) -> Self:
        """Return an empty object."""
        return FacetBuckets(buckets=[])


@final
class SolrBucketFacetResponse(BaseModel, frozen=True):
    """The response to 'bucket' facet requests, like terms and range.

    See: https://solr.apache.org/guide/solr/latest/query-guide/json-facet-api.html#types-of-facets
    """

    count: int
    buckets: dict[FieldName, FacetBuckets]

    def get_counts(self, field: FieldName) -> FacetBuckets:
        """Return the facet buckets associated to the given field."""
        v = self.buckets.get(field)
        return v if v is not None else FacetBuckets.empty()

    @model_serializer()
    def to_dict(self) -> dict[str, Any]:
        """Return the dict of this object."""
        result: dict[str, Any] = {"count": self.count}
        for key in self.buckets:
            result.update({key: self.buckets[key].to_dict()})

        return result

    @classmethod
    def empty(cls) -> SolrBucketFacetResponse:
        """Return an empty response."""
        return SolrBucketFacetResponse(count=0, buckets={})

    @model_validator(mode="wrap")
    @classmethod
    def _validate(
        cls, data: Any, handler: ModelWrapValidatorHandler[SolrBucketFacetResponse]
    ) -> SolrBucketFacetResponse:
        try:
            return handler(data)
        except ValidationError as err:
            if isinstance(data, dict):
                count: int | None = data.get("count")
                if count is not None:
                    buckets: dict[FieldName, FacetBuckets] = {}
                    for key in data:
                        if key != "count":
                            bb = FacetBuckets.model_validate(data[key])
                            buckets.update({key: bb})

                    return SolrBucketFacetResponse(count=count, buckets=buckets)
                else:
                    raise ValueError(f"No 'count' property in dict: {data}") from err
            else:
                raise ValueError(f"Expected a dict to, but got: {data}") from err


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
    facet: SolrFacets = Field(default_factory=SolrFacets.empty)

    def to_dict(self) -> dict[str, Any]:
        """Return the dict representation of this query."""
        return self.model_dump(exclude_defaults=True)

    def with_sort(self, s: list[tuple[FieldName, SortDirection]]) -> Self:
        """Return a copy of this with an updated sort."""
        return self.model_copy(update={"sort": s})

    def with_facets(self, fs: SolrFacets) -> Self:
        """Return a copy with the given facet requests."""
        return self.model_copy(update={"facet": fs})

    def with_facet(self, f: FacetTerms | FacetArbitraryRange) -> Self:
        """Return a copy with the given facet request added."""
        nf = self.facet.with_facet(f)
        return self.model_copy(update={"facet": nf})

    def add_sub_query(self, field: FieldName, sq: SubQuery) -> Self:
        """Add the sub query to this query."""
        np = self.params | sq.to_params(field)
        fs = self.fields + [FieldName(f"{field}:[subquery]")]
        return self.model_copy(update={"params": np, "fields": fs})

    def add_filter(self, *args: str) -> Self:
        """Return a copy with the given filter query added."""
        if len(args) == 0:
            return self
        else:
            fq = self.filter + list(args)
            return self.model_copy(update={"filter": fq})

    @field_serializer("sort", when_used="always")
    def __serialize_sort(self, sort: list[tuple[FieldName, SortDirection]]) -> str:
        return ",".join(list(map(lambda t: f"{t[0]} {t[1].value}", sort)))

    @classmethod
    def query_all_fields(cls, qstr: str, limit: int = 50, offset: int = 0) -> SolrQuery:
        """Create a query with defaults returning all fields of a document."""
        return SolrQuery(query=qstr, fields=["*", "score"], limit=limit, offset=offset)


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


DocVersion = NewType("DocVersion", int)
""" The `_version_` field can be used to enable optimistic concurrency control:
 https://solr.apache.org/guide/solr/latest/indexing-guide/partial-document-updates.html#optimistic-concurrency
"""


class DocVersions:
    """Possible values for the _version_ field."""

    @classmethod
    def not_exists(cls) -> DocVersion:
        """Specifies a version requiring a document to not exist."""
        return DocVersion(-1)

    @classmethod
    def exists(cls) -> DocVersion:
        """Specifies a version requiring a document to exist."""
        return DocVersion(1)

    @classmethod
    def off(cls) -> DocVersion:
        """Specifies a version indicating no version requirement.

        Optimistic concurrency control is not used. With this value a
        document will be overwritting if it exists or inserted.
        """
        return DocVersion(0)

    @classmethod
    def exact(cls, n: int) -> DocVersion:
        """Specifies an exact version."""
        return DocVersion(n)


type UpsertResponse = UpsertSuccess | Literal["VersionConflict"]


class SolrDocument(Protocol):
    """The base for a document in SOLR.

    All documents should have an `id` property denoting their primary identity.
    """

    @property
    def id(self) -> str:
        """The document id."""
        ...

    def to_dict(self) -> dict[str, Any]:
        """Return a dict representation of this document."""
        ...


@dataclass
class RawDocument(SolrDocument):
    """A simple wrapper around a JSON dictionary."""

    data: dict[str, Any]

    @property
    def id(self) -> str:
        """Return the document id."""
        return str(self.data["id"])

    def to_dict(self) -> dict[str, Any]:
        """Return the data dictionary."""
        return self.data


class ResponseBody(BaseModel):
    """The body of a search response."""

    num_found: int = Field(serialization_alias="numFound", validation_alias=AliasChoices("numFound", "num_found"))
    start: int
    num_found_exact: bool = Field(
        serialization_alias="numFoundExact", validation_alias=AliasChoices("numFoundExact", "num_found_exact")
    )
    docs: list[dict[str, Any]]

    def read_to[A](self, f: Callable[[dict[str, Any]], A | None]) -> list[A]:
        """Read the documents array using the given function."""
        result = []
        for doc in self.docs:
            a = f(doc)
            if a is not None:
                result.append(a)

        return result


class QueryResponse(BaseModel):
    """The complete response object for running a query.

    Note, solr doesn't set the `responseHeader` for get-by-id requests. Otherwise it will be set.
    """

    responseHeader: ResponseHeader = Field(
        serialization_alias="responseHeader",
        validation_alias=AliasChoices("responseHeader", "response_header"),
        default_factory=lambda: ResponseHeader(status=200),
    )
    facets: SolrBucketFacetResponse = Field(default_factory=SolrBucketFacetResponse.empty)
    response: ResponseBody


class SolrClientConnectException(SolrClientException):
    """Error when connecting to solr fails."""

    def __init__(self, cause: ConnectError):
        super().__init__(f"Connecting to solr at '{cause.request.url}' failed: {cause}", code=1503, status_code=503)


class SolrClientGetByIdException(SolrClientException):
    """Error when a lookup by document id failed."""

    def __init__(self, id: str, resp: Response):
        super().__init__(
            f"Lookup solr document by id {id} failed with unexpected status {resp.status_code} ({resp.text})"
        )


class SolrClientQueryException(SolrClientException):
    """Error when querying failed."""

    def __init__(self, query: SolrQuery, resp: Response):
        super().__init__(
            f"Querying solr with '{query.to_dict()}' failed with unexpected status {resp.status_code} ({resp.text})"
        )


class SolrClientUpsertException(SolrClientException):
    """Error when upserting."""

    def __init__(self, docs: list[SolrDocument], resp: Response):
        count = len(docs)
        super().__init__(f"Inserting {count} documents failed with status {resp.status_code} ({resp.text})")


class SolrClientStatusException(SolrClientException):
    """Error when obtaining the status of the core."""

    def __init__(self, cfg: SolrClientConfig, resp: Response):
        super().__init__(f"Error getting the status of core {cfg.core}. {resp.status_code}/{resp.text}")


class SolrClientCreateCoreException(SolrClientException):
    """Error when creating a core."""

    def __init__(self, core: str, resp: Response):
        super().__init__(f"Error creating core '{core}': {resp.status_code}/{resp.text}")


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

    @abstractmethod
    async def delete(self, query: str) -> Response:
        """Delete data that matches the `query`."""
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

    def __repr__(self) -> str:
        return f"DefaultSolrClient(delegate={self.delegate}, config={self.config})"

    async def __aenter__(self) -> Self:
        await self.delegate.__aenter__()
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        return await self.delegate.__aexit__(exc_type, exc, tb)

    async def get_raw(self, id: str) -> Response:
        """Query documents and return the http response."""
        try:
            return await self.delegate.get("/get", params={"wt": "json", "ids": id})
        except ConnectError as e:
            raise SolrClientConnectException(e) from e

    async def query_raw(self, query: SolrQuery) -> Response:
        """Query documents and return the http response."""
        try:
            logger.debug(f"Running solr query: {self.config.base_url}/solr/{self.config.core}")
            return await self.delegate.post("/query", params={"wt": "json"}, json=query.to_dict())
        except ConnectError as e:
            raise SolrClientConnectException(e) from e

    async def get(self, id: str) -> QueryResponse:
        """Get a document by id, returning a `QueryResponse`."""
        resp = await self.get_raw(id)
        if not resp.is_success:
            raise SolrClientGetByIdException(id, resp)
        else:
            return QueryResponse.model_validate(resp.json())

    async def query(self, query: SolrQuery) -> QueryResponse:
        """Query documents, returning a `QueryResponse`."""
        resp = await self.query_raw(query)
        if not resp.is_success:
            raise SolrClientQueryException(query, resp)
        else:
            return QueryResponse.model_validate(resp.raise_for_status().json())

    async def modify_schema(self, cmds: SchemaCommandList) -> Response:
        """Updates the schema with the given commands."""
        data = cmds.to_json()
        logger.debug(f"modify schema: {data}")
        try:
            return await self.delegate.post(
                "/schema",
                params={"commit": "true", "overwrite": "true"},
                content=data.encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
        except ConnectError as e:
            raise SolrClientConnectException(e) from e

    async def upsert(self, docs: list[SolrDocument]) -> UpsertResponse:
        """Inserts or updates a document in SOLR.

        The `_version_` property determines wether optimistic locking is used. In this
        case the result is either expected to be successful or a version conflict. All
        other outcomes are raised as an exception.
        """
        j = json.dumps([e.to_dict() for e in docs])
        logger.debug(f"upserting: {j}")
        try:
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
                    raise SolrClientUpsertException(docs, res) from None
        except ConnectError as e:
            raise SolrClientConnectException(e) from e

    async def get_schema(self) -> CoreSchema:
        """Return the current schema."""
        resp = await self.delegate.get("/schema")
        cs = CoreSchema.model_validate(resp.json()["schema"])
        return cs

    async def delete(self, query: str) -> Response:
        """Delete all documents that matches `query`."""
        cmd = {"delete": {"query": query}}
        return await self.delegate.post(
            "/update",
            params={"commit": "true"},
            content=json.dumps(cmd).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )

    async def close(self) -> None:
        """Close this client and free resources."""
        return await self.delegate.aclose()


class SolrAdminClient(AbstractAsyncContextManager, ABC):
    """A client to the core admin api.

    Url: https://solr.apache.org/guide/solr/latest/configuration-guide/coreadmin-api.html
    """

    @abstractmethod
    async def core_status(self, core_name: str | None) -> dict[str, Any] | None:
        """Return the status of the connected core."""
        ...

    @abstractmethod
    async def create(self, core_name: str | None) -> None:
        """Create a core."""
        ...


class DefaultSolrAdminClient(SolrAdminClient):
    """A client to the core admin api.

    Url: https://solr.apache.org/guide/solr/latest/configuration-guide/coreadmin-api.html
    """

    delegate: AsyncClient
    config: SolrClientConfig

    def __init__(self, cfg: SolrClientConfig):
        self.config = cfg
        url_parsed = list(urlparse(cfg.base_url))
        url_parsed[2] = urljoin(url_parsed[2], "/api/cores")
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

    async def core_status(self, core_name: str | None) -> dict[str, Any] | None:
        """Return the status of the connected core or the one given by `core_name`."""
        core = core_name or self.config.core
        resp = await self.delegate.get(f"/{core}")
        if not resp.is_success:
            raise SolrClientStatusException(self.config, resp)
        else:
            data = resp.json()["status"][self.config.core]
            # if the core doesn't exist, solr returns 200 with an empty body
            return data if data.get("name") == self.config.core else None

    async def create(self, core_name: str | None) -> None:
        """Create a core with the given `core_name` or the name provided in the config object."""
        core = core_name or self.config.core
        data = {"create": {"name": core, "configSet": self.config.configset}}
        resp = await self.delegate.post("", json=data)
        if not resp.is_success:
            raise SolrClientCreateCoreException(core, resp)
        else:
            return None
