"""Shared fixtures for MCP server tests."""

from __future__ import annotations

import asyncio
import contextlib
import datetime
import json
from typing import Any
from unittest.mock import AsyncMock

import pytest
from mcp.client.session import ClientSession
from mcp.shared.memory import create_client_server_memory_streams

from renku_data_services.mcp_api.dependencies import MCPDependencies
from renku_data_services.mcp_api.server import create_server, set_current_token


@pytest.fixture
def mock_deps() -> MCPDependencies:
    """MCPDependencies with a mocked api() method."""
    deps = MCPDependencies(base_url="https://test.renkulab.io")
    deps.api = AsyncMock(return_value={})
    return deps


@contextlib.asynccontextmanager
async def mcp_session(deps: MCPDependencies, token: str = "test-token"):
    """Async context manager that runs the MCP server in-process.
    Must be used within a single asyncio task to keep anyio cancel scopes happy."""
    set_current_token(token)
    server = create_server(deps)

    async with create_client_server_memory_streams() as (client_streams, server_streams):
        task = asyncio.create_task(
            server._mcp_server.run(
                server_streams[0],
                server_streams[1],
                server._mcp_server.create_initialization_options(),
            )
        )
        try:
            async with ClientSession(*client_streams) as session:
                await session.initialize()
                yield session, deps
        finally:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass


def tool_result_list(result: Any) -> list[Any]:
    """Parse a tool result that returns a list — one content block per item."""
    return [json.loads(c.text) for c in result.content]


def tool_result_dict(result: Any) -> dict[str, Any]:
    """Parse a tool result that returns a single object."""
    return json.loads(result.content[0].text)


def make_session(state: str, started_at: str | None = None, will_delete_at: str | None = None) -> dict[str, Any]:
    """Build a minimal session dict for test assertions."""
    s: dict[str, Any] = {"id": "test-session", "status": {"state": state}}
    if started_at:
        s["started_at"] = started_at
    if will_delete_at:
        s["will_delete_at"] = will_delete_at
    return s


def iso_ago(seconds: int) -> str:
    return (datetime.datetime.now(datetime.UTC) - datetime.timedelta(seconds=seconds)).isoformat()


def iso_future(seconds: int) -> str:
    return (datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=seconds)).isoformat()
