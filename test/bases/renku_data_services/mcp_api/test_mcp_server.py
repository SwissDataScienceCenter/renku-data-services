"""Tests for the Renku MCP server."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from renku_data_services.mcp_api.dependencies import MCPDependencies
from renku_data_services.mcp_api.server import _is_stale_session, _launcher_summary, _project_path
from test.bases.renku_data_services.mcp_api.conftest import (
    iso_ago,
    iso_future,
    make_session,
    mcp_session,
    tool_result_dict,
    tool_result_list,
)


# ------------------------------------------------------------------ #
# Pure logic — no server needed                                        #
# ------------------------------------------------------------------ #


class TestIsStaleSession:
    def test_no_will_delete_at(self):
        assert _is_stale_session({}) is False

    def test_future_delete_at(self):
        assert _is_stale_session({"will_delete_at": iso_future(3600)}) is False

    def test_past_delete_at(self):
        assert _is_stale_session({"will_delete_at": iso_ago(60)}) is True

    def test_malformed_timestamp(self):
        assert _is_stale_session({"will_delete_at": "not-a-date"}) is False


class TestLauncherSummary:
    def test_adds_handoff_block(self):
        data = {
            "id": "launcher-1",
            "resource_class_id": 5,
            "environment": {
                "id": "env-1",
                "container_image": "renku/renkulab:latest",
                "port": 8888,
                "command": ["/cnb/lifecycle/launcher"],
                "args": [],
            },
        }
        result = _launcher_summary(data)
        assert result["_handoff"]["launcher_id"] == "launcher-1"
        assert result["_handoff"]["environment_id"] == "env-1"
        assert result["_handoff"]["resource_class_id"] == 5
        assert result["_handoff"]["container_image"] == "renku/renkulab:latest"
        assert result["_handoff"]["port"] == 8888

    def test_missing_environment(self):
        data = {"id": "launcher-1", "resource_class_id": 5}
        result = _launcher_summary(data)
        assert result["_handoff"]["launcher_id"] == "launcher-1"
        assert result["_handoff"]["environment_id"] is None


class TestProjectPath:
    def test_id_only(self):
        assert _project_path("abc123") == "/projects/abc123"

    def test_namespace_slug(self):
        assert _project_path("myuser/my-project") == "/namespaces/myuser/projects/my-project"

    def test_special_chars_encoded(self):
        path = _project_path("my user/my project")
        assert " " not in path


# ------------------------------------------------------------------ #
# MCPDependencies.api — test via pytest-httpx                         #
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_api_sets_auth_header(httpx_mock):
    httpx_mock.add_response(json={"ok": True})
    deps = MCPDependencies(base_url="https://test.renkulab.io")
    await deps.api("GET", "/projects", "my-token")

    request = httpx_mock.get_request()
    assert request.headers["Authorization"] == "Bearer my-token"
    assert request.headers["Accept"] == "application/json"


@pytest.mark.asyncio
async def test_api_constructs_correct_url(httpx_mock):
    httpx_mock.add_response(json=[])
    deps = MCPDependencies(base_url="https://test.renkulab.io")
    await deps.api("GET", "/projects", "tok", query={"namespace": "myuser"})

    request = httpx_mock.get_request()
    assert str(request.url).startswith("https://test.renkulab.io/api/data/projects")
    assert "namespace=myuser" in str(request.url)


@pytest.mark.asyncio
async def test_api_raises_on_http_error(httpx_mock):
    httpx_mock.add_response(status_code=403, text="Forbidden")
    deps = MCPDependencies(base_url="https://test.renkulab.io")

    with pytest.raises(RuntimeError, match="HTTP 403"):
        await deps.api("GET", "/projects", "tok")


@pytest.mark.asyncio
async def test_api_returns_headers_when_requested(httpx_mock):
    httpx_mock.add_response(json={"id": "1"}, headers={"ETag": '"abc123"'})
    deps = MCPDependencies(base_url="https://test.renkulab.io")
    result, headers = await deps.api("GET", "/projects/1", "tok", return_headers=True)

    assert result == {"id": "1"}
    assert "etag" in {k.lower() for k in headers}


# ------------------------------------------------------------------ #
# Tool behaviour — in-process MCP + mocked deps                       #
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_list_tools_smoke(mock_deps):
    """Server exposes all expected tools."""
    async with mcp_session(mock_deps) as (session, _):
        result = await session.list_tools()
        names = {t.name for t in result.tools}
        assert "project_list" in names
        assert "job_run" in names
        assert "session_delete_if_failed" in names
        assert "build_wait" in names
        assert len(names) == 41


@pytest.mark.asyncio
async def test_session_list_filters_stale(mock_deps):
    mock_deps.api.return_value = [
        make_session("running"),
        make_session("hibernated", will_delete_at=iso_ago(60)),    # stale
        make_session("running", will_delete_at=iso_future(3600)),  # not stale
    ]

    async with mcp_session(mock_deps) as (session, _):
        result = await session.call_tool("session_list", {})
        sessions = tool_result_list(result)
        assert len(sessions) == 2
        assert all(s["status"]["state"] == "running" for s in sessions)


@pytest.mark.asyncio
async def test_job_run_marks_new_session(mock_deps):
    """job_run sets _created=True when started_at is recent."""
    mock_deps.api.return_value = make_session("running", started_at=iso_ago(5))

    async with mcp_session(mock_deps) as (session, _):
        result = await session.call_tool("job_run", {"launcher_id": "launcher-1"})
        data = tool_result_dict(result)
        assert data["_created"] is True


@pytest.mark.asyncio
async def test_job_run_marks_stale_session(mock_deps):
    """job_run sets _created=False when the platform returned a pre-existing session."""
    mock_deps.api.return_value = make_session("running", started_at=iso_ago(300))

    async with mcp_session(mock_deps) as (session, _):
        result = await session.call_tool("job_run", {"launcher_id": "launcher-1"})
        data = tool_result_dict(result)
        assert data["_created"] is False


@pytest.mark.asyncio
async def test_session_delete_if_failed_deletes_terminal_states(mock_deps):
    """session_delete_if_failed deletes sessions in any terminal state."""
    async with mcp_session(mock_deps) as (session, deps):
        for state in ("failed", "error", "stopped", "succeeded", "completed", "finished"):
            deps.api.reset_mock()
            deps.api.return_value = make_session(state)
            result = await session.call_tool("session_delete_if_failed", {"session_id": "s1"})
            assert "Deleted" in result.content[0].text, f"Expected deletion for state '{state}'"
            assert deps.api.call_count == 2, f"Expected GET + DELETE for state '{state}'"


@pytest.mark.asyncio
async def test_session_delete_if_failed_skips_running(mock_deps):
    """session_delete_if_failed does not delete running sessions."""
    mock_deps.api.return_value = make_session("running")

    async with mcp_session(mock_deps) as (session, deps):
        result = await session.call_tool("session_delete_if_failed", {"session_id": "s1"})
        assert "not deleted" in result.content[0].text
        assert deps.api.call_count == 1  # only the GET


@pytest.mark.asyncio
async def test_job_wait_returns_timed_out_flag(mock_deps):
    """job_wait returns timed_out=True instead of raising when it times out."""
    async def fake_api(method, path, token, *args, **kwargs):
        if "/logs" in path:
            return {}
        return make_session("starting")

    mock_deps.api.side_effect = fake_api

    async with mcp_session(mock_deps) as (session, _):
        result = await session.call_tool("job_wait", {"session_id": "s1", "timeout": 1, "interval": 1})
        data = tool_result_dict(result)
        assert data["timed_out"] is True
        assert "state" in data


@pytest.mark.asyncio
async def test_project_create_sends_correct_body(mock_deps):
    """project_create passes name, namespace, and visibility to the API."""
    mock_deps.api.return_value = {"id": "new-proj", "name": "My Project"}

    async with mcp_session(mock_deps) as (session, deps):
        await session.call_tool(
            "project_create",
            {"name": "My Project", "namespace": "myuser", "visibility": "public"},
        )
        deps.api.assert_called_once()
        _, path, _, body = deps.api.call_args.args
        assert path == "/projects"
        assert body["name"] == "My Project"
        assert body["namespace"] == "myuser"
        assert body["visibility"] == "public"
