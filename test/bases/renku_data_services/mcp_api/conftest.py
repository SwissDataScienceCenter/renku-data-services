"""Shared fixtures for MCP server tests."""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import Any
from unittest.mock import AsyncMock

import pytest
from mcp import types
from mcp.client.session import ClientSession
from mcp.shared.memory import create_client_server_memory_streams

from renku_data_services.mcp_api.client import RenkuApiClient
from renku_data_services.mcp_api.server import create_server, set_current_token


@pytest.fixture
def mock_api() -> RenkuApiClient:
    """RenkuApiClient with a mocked request() method."""
    api = RenkuApiClient(base_url="https://test.renkulab.io")
    api.request = AsyncMock(return_value={})
    return api


def elicitation_callback(answer: bool | None):
    """Build a client elicitation handler that answers confirmations for us.

    Passing one makes the test client declare the elicitation capability, which is what the
    server checks before it will ask. `answer=None` declines the request, as a user clicking
    "no" would; True and False both accept and return that value for the `confirm` field.
    """

    async def _callback(context, params):
        if answer is None:
            return types.ElicitResult(action="decline")
        return types.ElicitResult(action="accept", content={"confirm": answer})

    return _callback


@contextlib.asynccontextmanager
async def mcp_session(api: RenkuApiClient, token: str = "test-token", elicit: bool | None = ...):  # type: ignore[assignment]
    """Async context manager that runs the MCP server in-process.
    Must be used within a single asyncio task to keep anyio cancel scopes happy.

    By default the client declares no elicitation capability, matching a client that cannot
    prompt. Pass elicit=True/False/None to declare it and answer accordingly.
    """
    set_current_token(token)
    server = create_server(api)
    callback = None if elicit is ... else elicitation_callback(elicit)

    async with create_client_server_memory_streams() as (client_streams, server_streams):
        task = asyncio.create_task(
            server._mcp_server.run(
                server_streams[0],
                server_streams[1],
                server._mcp_server.create_initialization_options(),
            )
        )
        try:
            async with ClientSession(*client_streams, elicitation_callback=callback) as session:
                await session.initialize()
                yield session, api
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task


def tool_result_list(result: Any) -> list[Any]:
    """Parse a tool result that returns a list — one content block per item."""
    return [json.loads(c.text) for c in result.content]


def tool_result_dict(result: Any) -> dict[str, Any]:
    """Parse a tool result that returns a single object."""
    return json.loads(result.content[0].text)


def make_session(state: str) -> dict[str, Any]:
    """Build a minimal session dict for test assertions."""
    return {"id": "test-session", "status": {"state": state}}
