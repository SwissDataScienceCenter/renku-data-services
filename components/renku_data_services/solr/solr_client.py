"""This defines an interface to SOLR."""

from dataclasses import dataclass
from typing import Any, AsyncContextManager, Optional, Protocol, final, Self

from asyncio.streams import logger
from httpx import AsyncClient, BasicAuth, Response
import urllib

from pydantic import BaseModel, Field
from renku_data_services.solr.solr_schema import SchemaCommandList


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
    user: Optional[SolrUser]


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


class SolrClient(Protocol):
    """A client to SOLR."""

    async def close(self) -> None:
        """Shuts down this client."""
        ...

    async def get_raw(self, id: str) -> Response: ...

    async def query_raw(self, query: SolrQuery) -> Response: ...

    async def modify_schema(self, cmds: SchemaCommandList) -> Response: ...


class DefaultSolrClient(SolrClient, AsyncContextManager):
    """Default implementation of the solr client."""

    delegate: AsyncClient
    config: SolrClientConfig

    def __init__(self, cfg: SolrClientConfig):
        self.config = cfg
        bauth = BasicAuth(username=cfg.user.username, password=cfg.user.password) if cfg.user is not None else None
        burl = cfg.base_url + "/solr/" + cfg.core
        self.delegate = AsyncClient(auth=bauth, base_url=burl, timeout=6000)

    async def __aenter__(self) -> Self:
        await self.delegate.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return await self.delegate.__aexit__(exc_type, exc, tb)

    async def get_raw(self, id: str) -> Response:
        return await self.delegate.get(f"/get?wt=json&indent=true&ids={id}")

    async def query_raw(self, query: SolrQuery) -> Response:
        return await self.delegate.post(f"/query?wt=json&indent=true", json=query.to_dict())

    async def modify_schema(self, cmds: SchemaCommandList) -> Response:
        data = cmds.to_json()
        logger.info(f"modify schema: {data}")
        return await self.delegate.post(
            "/schema?commit=true",
            content=data.encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )

    async def close(self) -> None:
        """Close this client and free resources."""
        return await self.delegate.aclose()
