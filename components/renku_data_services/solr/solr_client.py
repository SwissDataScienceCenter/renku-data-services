"""This defines an interface to SOLR."""

from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
import logging

from enum import Enum
from types import TracebackType
from urllib.parse import urljoin, urlparse, urlencode, urlunparse
import json
from typing import Any, Literal, Optional, Protocol, final, Self

from httpx import AsyncClient, BasicAuth, Response

from pydantic import AliasChoices, BaseModel, Field
from renku_data_services.solr.solr_schema import SchemaCommandList, CoreSchema


@dataclass
@final
class SolrUser:
    username: str
    password: str


@dataclass
@final
class SolrClientConfig:
    base_url: str
    core: str
    user: Optional[SolrUser] = None
    timeout: int = 600


@final
class SolrQuery(BaseModel):
    query: str
    filter: list[str] = Field(default_factory=list)
    limit: int = 50
    offset: int = 0
    fields: list[str] = Field(default_factory=list)
    params: dict[str, str] = Field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(exclude_unset=True)

    @classmethod
    def query_all(cls, qstr: str) -> Self:
        return SolrQuery(query=qstr, fields=["*"])


@final
class ResponseHeader(BaseModel):
    status: int
    queryTime: int = Field(serialization_alias="QTime", validation_alias=AliasChoices("QTime", "queryTime"), default=0)
    params: dict[str, str] = Field(default_factory=dict)


@final
class UpsertSuccess(BaseModel):
    header: ResponseHeader


class DocVersion(Enum):
    not_exists = -1
    exists = 1
    off = 0

    @classmethod
    def exact(cls, n: int) -> int:
        return n


type UpsertResponse = UpsertSuccess | Literal["VersionConflict"]


class SolrDocument(Protocol):
    id: str

    def to_dict(self) -> dict[str, Any]:
        """Return a dict representation of this document."""


class ResponseBody(BaseModel):
    numFound: int
    start: int
    numFoundExact: bool
    docs: list[dict[str, Any]]


class QueryResponse(BaseModel):
    responseHeader: ResponseHeader = ResponseHeader(status=200)
    response: ResponseBody


class SolrClient(Protocol):
    """A client to SOLR."""

    async def close(self) -> None:
        """Shuts down this client."""

    async def get_raw(self, id: str) -> Response: ...

    async def query_raw(self, query: SolrQuery) -> Response: ...

    async def get(self, id: str) -> QueryResponse: ...

    async def query(self, query: SolrQuery) -> QueryResponse: ...

    async def modify_schema(self, cmds: SchemaCommandList) -> Response: ...

    async def upsert(self, docs: list[SolrDocument]) -> UpsertResponse: ...

    async def get_schema(self) -> CoreSchema: ...


class DefaultSolrClient(SolrClient, AbstractAsyncContextManager):
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

    def _make_url(self, path: str, qp: dict[str, Any]) -> str:
        qp.update({"wt": "json"})
        return f"{path}?{urlencode(qp)}"

    async def __aenter__(self) -> Self:
        await self.delegate.__aenter__()
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        return await self.delegate.__aexit__(exc_type, exc, tb)

    async def get_raw(self, id: str) -> Response:
        url = self._make_url("/get", {"ids": id})
        return await self.delegate.get(url)

    async def query_raw(self, query: SolrQuery) -> Response:
        url = self._make_url("/query", {})
        return await self.delegate.post(url, json=query.to_dict())

    async def get(self, id: str) -> QueryResponse:
        resp = await self.get_raw(id)
        return QueryResponse.model_validate(resp.raise_for_status().json())

    async def query(self, query: SolrQuery) -> QueryResponse:
        resp = await self.query_raw(query)
        return QueryResponse.model_validate(resp.raise_for_status().json())

    async def modify_schema(self, cmds: SchemaCommandList) -> Response:
        """Updates the schema with the given commands."""
        data = cmds.to_json()
        logging.debug(f"modify schema: {data}")
        url = self._make_url("/schema", {"commit": "true", "overwrite": "true"})
        return await self.delegate.post(
            url,
            content=data.encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )

    async def upsert(self, docs: list[SolrDocument]) -> UpsertResponse:
        """Inserts or updates a document in SOLR.

        The `_version_` property determines wether optimistic locking is used. In this
        case the result is either expected to be successful or a version conflict. All
        other outcomes are raised as an exception.
        """
        j = json.dumps(list(map(lambda e: e.to_dict(), docs)))
        logging.debug(f"upserting: {j}")
        url = self._make_url("/update", {"commit": "true"})
        res = await self.delegate.post(url, content=j.encode("utf-8"), headers={"Content-Type": "application/json"})
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
