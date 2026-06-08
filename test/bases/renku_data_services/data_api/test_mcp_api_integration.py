"""Integration tests for the MCP server against the real data service API.

These tests verify that the API calls the MCP tools make are compatible with the
current API definition in this repo. They use the same Sanic test infrastructure as
the other data_api tests — a real DB, real SpiceDB, and a dummy authenticator.

The MCP tools are exercised via the full MCP protocol (in-process), routing API calls
through the Sanic test client instead of httpx.
"""

from __future__ import annotations

from typing import Any

import pytest
from sanic_testing.testing import SanicASGITestClient

from renku_data_services.mcp_api.dependencies import MCPDependencies
from renku_data_services.mcp_api.server import _admin_cache
from test.bases.renku_data_services.mcp_api.conftest import (
    mcp_session,
    tool_result_dict,
    tool_result_list,
)


class SanicMCPDependencies(MCPDependencies):
    """MCPDependencies that routes api() calls through the Sanic test client."""

    def __init__(self, sanic_client: SanicASGITestClient) -> None:
        super().__init__(base_url="http://localhost")
        self._client = sanic_client

    async def api(
        self,
        method: str,
        path: str,
        token: str,
        body: Any = None,
        *,
        query: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
        return_headers: bool = False,
    ) -> Any:
        headers: dict[str, str] = {"Authorization": f"Bearer {token}"}
        if extra_headers:
            headers.update(extra_headers)

        _, response = await self._client.request(
            method,
            f"/api/data{path}",
            headers=headers,
            json=body,
            params=query,
        )

        if response.status >= 400:
            raise RuntimeError(f"HTTP {response.status}: {response.text}")

        result = response.json if response.content_type and "json" in response.content_type else None
        if return_headers:
            return result, dict(response.headers)
        return result


@pytest.fixture(autouse=True)
def clear_admin_cache_integration():
    _admin_cache.clear()
    yield
    _admin_cache.clear()


@pytest.fixture
def mcp_deps(sanic_client: SanicASGITestClient) -> SanicMCPDependencies:
    return SanicMCPDependencies(sanic_client)


# ---------------------------------------------------------------------------
# Platform / auth
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auth_status(mcp_deps: SanicMCPDependencies, regular_user_access_token: str) -> None:
    async with mcp_session(mcp_deps, token=regular_user_access_token) as (session, _):
        result = await session.call_tool("auth_status", {})
        data = tool_result_dict(result)
        assert data["authenticated"] is True
        assert data["is_admin"] is False


@pytest.mark.asyncio
async def test_resource_classes(mcp_deps: SanicMCPDependencies, regular_user_access_token: str) -> None:
    async with mcp_session(mcp_deps, token=regular_user_access_token) as (session, _):
        result = await session.call_tool("resource_classes", {})
        classes = tool_result_list(result)
        # Resource pools may not be seeded in all test environments
        assert isinstance(classes, list)
        if classes:
            assert all("id" in c and "cpu" in c for c in classes)


@pytest.mark.asyncio
async def test_namespaces(mcp_deps: SanicMCPDependencies, regular_user_access_token: str) -> None:
    async with mcp_session(mcp_deps, token=regular_user_access_token) as (session, _):
        result = await session.call_tool("namespaces", {})
        ns_list = tool_result_list(result)
        assert len(ns_list) > 0


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_project_list(mcp_deps: SanicMCPDependencies, regular_user_access_token: str) -> None:
    async with mcp_session(mcp_deps, token=regular_user_access_token) as (session, _):
        result = await session.call_tool("project_list", {})
        assert result.isError is not True


@pytest.mark.asyncio
async def test_project_create_and_delete(
    mcp_deps: SanicMCPDependencies, regular_user_access_token: str, regular_user: Any
) -> None:
    namespace = regular_user.namespace.path.serialize()
    async with mcp_session(mcp_deps, token=regular_user_access_token) as (session, _):
        created = await session.call_tool(
            "project_create",
            {"name": "mcp-integration-test", "namespace": namespace, "visibility": "private"},
        )
        assert created.isError is not True
        project = tool_result_dict(created)
        project_id = project["id"]

        deleted = await session.call_tool("project_delete", {"project": project_id})
        assert deleted.isError is not True


# ---------------------------------------------------------------------------
# Launcher create — API compatibility regression tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_launcher_create_without_launcher_type(
    mcp_deps: SanicMCPDependencies,
    regular_user_access_token: str,
    regular_user: Any,
    create_session_environment: Any,
    create_resource_pool: Any,
) -> None:
    """Launcher creation without launcher_type must not return 422.

    Regression test: launcher_type was added to POST /session_launchers in a recent
    API change. Sending launcher_type='interactive' fails on older deployments because
    their schema has extra='forbid'. The MCP server must omit launcher_type when not
    explicitly set.
    """
    env = await create_session_environment("mcp-test-env")
    pool = await create_resource_pool(admin=True)
    resource_class_id = pool["classes"][0]["id"]

    namespace = regular_user.namespace.path.serialize()
    async with mcp_session(mcp_deps, token=regular_user_access_token) as (session, _):
        project_result = await session.call_tool(
            "project_create",
            {"name": "mcp-launcher-test", "namespace": namespace, "visibility": "private"},
        )
        project_id = tool_result_dict(project_result)["id"]
        try:
            # Do NOT pass launcher_type — this is the key assertion
            launcher_result = await session.call_tool(
                "launcher_create",
                {
                    "project_id": project_id,
                    "name": "test-launcher",
                    "resource_class_id": resource_class_id,
                    "environment": {"id": env["id"]},
                },
            )
            assert (
                launcher_result.isError is not True
            ), f"launcher_create failed without launcher_type: {launcher_result.content[0].text}"
            launcher_id = tool_result_dict(launcher_result)["id"]
            await session.call_tool("launcher_delete", {"launcher_id": launcher_id})
        finally:
            await session.call_tool("project_delete", {"project": project_id})


@pytest.mark.asyncio
async def test_launcher_create_non_interactive(
    mcp_deps: SanicMCPDependencies,
    regular_user_access_token: str,
    regular_user: Any,
    create_session_environment: Any,
    create_resource_pool: Any,
) -> None:
    """Launcher creation with launcher_type='non_interactive' must succeed on current API."""
    env = await create_session_environment("mcp-job-env")
    pool = await create_resource_pool(admin=True)
    resource_class_id = pool["classes"][0]["id"]

    namespace = regular_user.namespace.path.serialize()
    async with mcp_session(mcp_deps, token=regular_user_access_token) as (session, _):
        project_result = await session.call_tool(
            "project_create",
            {"name": "mcp-job-test", "namespace": namespace, "visibility": "private"},
        )
        project_id = tool_result_dict(project_result)["id"]
        try:
            launcher_result = await session.call_tool(
                "launcher_create",
                {
                    "project_id": project_id,
                    "name": "test-job-launcher",
                    "resource_class_id": resource_class_id,
                    "environment": {"id": env["id"]},
                    "launcher_type": "non_interactive",
                },
            )
            assert launcher_result.isError is not True
            launcher = tool_result_dict(launcher_result)
            assert launcher.get("launcher_type") == "non_interactive"
            await session.call_tool("launcher_delete", {"launcher_id": launcher["id"]})
        finally:
            await session.call_tool("project_delete", {"project": project_id})
