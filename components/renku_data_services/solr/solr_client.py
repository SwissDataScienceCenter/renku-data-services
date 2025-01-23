"""This defines an interface to SOLR."""

from abc import ABC, abstractmethod

import aiosolr
import aiohttp


class SolrClient(ABC):
    """A client to SOLR."""

    @abstractmethod
    async def close(self) -> None:
        """Shuts down this client."""
        ...

    @abstractmethod
    async def get(self, id: str) -> aiosolr.Response:
        """Gets a single document by its id."""
        ...

    @abstractmethod
    async def query(self, query: str) -> aiosolr.Response:
        """Queries solr."""
        ...


class DefaultSolrClient(SolrClient):
    """Default implementation of the solr client."""
    delegate: aiosolr.Client

    def __init__(self, url: str):
        sc = aiosolr.Client(
            connection_url=url,
            client_timeout=aiohttp.ClientTimeout(total=5 * 60, sock_read=30),
        )
        self.delegate = sc

    async def async_init(self):
        """Async init."""
        await self.delegate.setup()
        return self

    def __await__(self):
        return self.async_init().__await__()

    async def get(self, id: str) -> aiosolr.Response:
        """Get a single document by its id."""
        return await self.delegate.get(id)

    async def query(self, query: str) -> aiosolr.Response:
        """Query solr."""
        return await self.delegate.query(q=query)

    async def close(self) -> None:
        """Close this client and free resources."""
        return await self.delegate.close()
