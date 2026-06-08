"""Tests for the Renku MCP server."""

from __future__ import annotations

from typing import Any

import pytest

from renku_data_services.mcp_api.dependencies import MCPDependencies
from renku_data_services.mcp_api.main import _authorization_server_doc, _protected_resource_doc
from renku_data_services.mcp_api.server import (
    _admin_cache,
    _is_stale_session,
    _launcher_summary,
    _project_path,
)
from test.bases.renku_data_services.mcp_api.conftest import (
    iso_ago,
    iso_future,
    make_session,
    mcp_session,
    tool_result_dict,
    tool_result_list,
)


@pytest.fixture(autouse=True)
def clear_admin_cache():
    """Ensure the admin cache doesn't bleed between tests."""
    _admin_cache.clear()
    yield
    _admin_cache.clear()


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
# OAuth metadata handlers                                              #
# ------------------------------------------------------------------ #


def test_protected_resource_doc_with_keycloak():
    doc = _protected_resource_doc("https://renkulab.io", "https://renkulab.io/auth/realms/Renku")
    assert doc["resource"] == "https://renkulab.io/mcp"
    assert doc["authorization_servers"] == ["https://renkulab.io/auth/realms/Renku"]


def test_protected_resource_doc_without_keycloak():
    doc = _protected_resource_doc("https://renkulab.io", "")
    assert "authorization_servers" not in doc


@pytest.mark.asyncio
async def test_authorization_server_doc_proxies_keycloak(httpx_mock):
    httpx_mock.add_response(
        json={
            "issuer": "https://renkulab.io/auth/realms/Renku",
            "authorization_endpoint": "https://renkulab.io/auth/realms/Renku/protocol/openid-connect/auth",
            "token_endpoint": "https://renkulab.io/auth/realms/Renku/protocol/openid-connect/token",
            "jwks_uri": "https://renkulab.io/auth/realms/Renku/protocol/openid-connect/certs",
            "registration_endpoint": "https://renkulab.io/auth/realms/Renku/clients-registrations/openid-connect",
        }
    )
    body, status = await _authorization_server_doc("https://renkulab.io/auth/realms/Renku")
    assert status == 200
    assert body["authorization_endpoint"] is not None
    assert body["token_endpoint"] is not None
    assert body["code_challenge_methods_supported"] == ["S256"]
    assert "registration_endpoint" not in body  # must be omitted to prevent DCR


@pytest.mark.asyncio
async def test_authorization_server_doc_no_keycloak_url():
    body, status = await _authorization_server_doc("")
    assert status == 503


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
# Admin check                                                          #
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_admin_blocks_tool_calls(mock_deps):
    """All tools except auth_status are blocked for admin users."""

    async def fake_api(method: str, path: str, token: str, *args: Any, **kwargs: Any) -> Any:
        if path == "/user":
            return {"is_admin": True, "id": "admin"}
        return []

    mock_deps.api.side_effect = fake_api

    async with mcp_session(mock_deps) as (session, _):
        result = await session.call_tool("project_list", {})
        assert result.isError is True
        assert "admin" in result.content[0].text.lower()


@pytest.mark.asyncio
async def test_non_admin_allowed(mock_deps):
    """Non-admin users can call tools normally."""

    async def fake_api(method: str, path: str, token: str, *args: Any, **kwargs: Any) -> Any:
        if path == "/user":
            return {"is_admin": False, "id": "user1"}
        return []

    mock_deps.api.side_effect = fake_api

    async with mcp_session(mock_deps) as (session, _):
        result = await session.call_tool("project_list", {})
        assert result.isError is not True


@pytest.mark.asyncio
async def test_admin_check_cached(mock_deps):
    """/user is only called once per token, even across multiple tool calls."""

    async def fake_api(method: str, path: str, token: str, *args: Any, **kwargs: Any) -> Any:
        if path == "/user":
            return {"is_admin": False, "id": "user1"}
        return []

    mock_deps.api.side_effect = fake_api

    async with mcp_session(mock_deps) as (session, _):
        await session.call_tool("project_list", {})
        await session.call_tool("session_list", {})

    user_calls = [c for c in mock_deps.api.call_args_list if c.args[1] == "/user"]
    assert len(user_calls) == 1


@pytest.mark.asyncio
async def test_admin_override_env(mock_deps, monkeypatch):
    """RENKU_MCP_ALLOW_ADMIN=1 lets admin users through."""
    monkeypatch.setenv("RENKU_MCP_ALLOW_ADMIN", "1")

    async def fake_api(method: str, path: str, token: str, *args: Any, **kwargs: Any) -> Any:
        if path == "/user":
            return {"is_admin": True, "id": "admin"}
        return []

    mock_deps.api.side_effect = fake_api

    async with mcp_session(mock_deps) as (session, _):
        result = await session.call_tool("project_list", {})
        assert result.isError is not True


# ------------------------------------------------------------------ #
# Tool behaviour — in-process MCP + mocked deps                       #
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_list_tools_smoke(mock_deps):
    """Server exposes the expected core tools."""
    async with mcp_session(mock_deps) as (session, _):
        result = await session.list_tools()
        names = {t.name for t in result.tools}
        for expected in (
            "auth_status",
            "project_list",
            "project_create",
            "project_update",
            "connector_create",
            "launcher_create",
            "launcher_delete",
            "session_launch",
            "session_wait",
            "job_run",
            "job_wait",
            "build_wait",
            "global_environments",
            "renku_group_members",
        ):
            assert expected in names, f"Missing tool: {expected}"


@pytest.mark.asyncio
async def test_session_list_filters_stale(mock_deps):
    mock_deps.api.return_value = [
        make_session("running"),
        make_session("hibernated", will_delete_at=iso_ago(60)),  # stale
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
    non_interactive_launcher = {"id": "launcher-1", "launcher_type": "non_interactive"}

    async def fake_api(method: str, path: str, token: str, *args: Any, **kwargs: Any) -> Any:
        if path == "/user":
            return {"is_admin": False}
        if method == "GET" and "session_launchers" in path:
            return non_interactive_launcher
        return make_session("running", started_at=iso_ago(5))

    mock_deps.api.side_effect = fake_api

    async with mcp_session(mock_deps) as (session, _):
        result = await session.call_tool("job_run", {"launcher_id": "launcher-1"})
        data = tool_result_dict(result)
        assert data["_created"] is True


@pytest.mark.asyncio
async def test_job_run_marks_stale_session(mock_deps):
    """job_run sets _created=False when the platform returned a pre-existing session."""
    non_interactive_launcher = {"id": "launcher-1", "launcher_type": "non_interactive"}

    async def fake_api(method: str, path: str, token: str, *args: Any, **kwargs: Any) -> Any:
        if path == "/user":
            return {"is_admin": False}
        if method == "GET" and "session_launchers" in path:
            return non_interactive_launcher
        return make_session("running", started_at=iso_ago(300))

    mock_deps.api.side_effect = fake_api

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
            paths = [c.args[1] for c in deps.api.call_args_list]
            assert "/sessions/s1" in paths, f"Expected GET /sessions/s1 for state '{state}'"
            methods = [c.args[0] for c in deps.api.call_args_list if c.args[1] == "/sessions/s1"]
            assert "DELETE" in methods, f"Expected DELETE for state '{state}'"


@pytest.mark.asyncio
async def test_session_delete_if_failed_skips_running(mock_deps):
    """session_delete_if_failed does not delete running sessions."""
    mock_deps.api.return_value = make_session("running")

    async with mcp_session(mock_deps) as (session, deps):
        result = await session.call_tool("session_delete_if_failed", {"session_id": "s1"})
        assert "not deleted" in result.content[0].text
        methods = [c.args[0] for c in deps.api.call_args_list if c.args[1] == "/sessions/s1"]
        assert "GET" in methods
        assert "DELETE" not in methods


@pytest.mark.asyncio
async def test_job_wait_returns_timed_out_flag(mock_deps):
    """job_wait returns timed_out=True instead of raising when it times out."""

    async def fake_api(method: str, path: str, token: str, *args: Any, **kwargs: Any) -> Any:
        if path == "/user":
            return {"is_admin": False}
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
        post_calls = [c for c in deps.api.call_args_list if c.args[0] == "POST"]
        assert len(post_calls) == 1
        _, path, _, body = post_calls[0].args
        assert path == "/projects"
        assert body["name"] == "My Project"
        assert body["namespace"] == "myuser"
        assert body["visibility"] == "public"


@pytest.mark.asyncio
async def test_project_repo_add_sends_etag(mock_deps):
    """project_repo_add fetches the ETag and passes it as If-Match on the PATCH."""
    project = {"id": "proj-1", "etag": '"v1"', "repositories": []}

    async def fake_api(method: str, path: str, token: str, body: Any = None, **kwargs: Any) -> Any:
        if path == "/user":
            return {"is_admin": False}
        if method == "GET" and kwargs.get("return_headers"):
            return project, {"ETag": '"v1"'}
        return {"id": "proj-1", "repositories": ["https://github.com/x/y"]}

    mock_deps.api.side_effect = fake_api

    async with mcp_session(mock_deps) as (session, deps):
        await session.call_tool("project_repo_add", {"project": "proj-1", "repository_url": "https://github.com/x/y"})

    patch_calls = [c for c in deps.api.call_args_list if c.args[0] == "PATCH"]
    assert len(patch_calls) == 1
    assert patch_calls[0].kwargs.get("extra_headers", {}).get("If-Match") == '"v1"'


@pytest.mark.asyncio
async def test_project_repo_add_raises_without_etag(mock_deps):
    """project_repo_add raises when the project has no ETag."""

    async def fake_api(method: str, path: str, token: str, *args: Any, **kwargs: Any) -> Any:
        if path == "/user":
            return {"is_admin": False}
        return {"id": "proj-1", "repositories": []}  # no etag field

    mock_deps.api.side_effect = fake_api

    async with mcp_session(mock_deps) as (session, _):
        result = await session.call_tool(
            "project_repo_add", {"project": "proj-1", "repository_url": "https://github.com/x/y"}
        )
        assert result.isError is True


@pytest.mark.asyncio
async def test_launcher_create_injects_name_for_image(mock_deps):
    """launcher_create adds 'name' to the environment dict for image-source environments."""
    mock_deps.api.return_value = {"id": "launcher-1", "environment": {}}

    async with mcp_session(mock_deps) as (session, deps):
        await session.call_tool(
            "launcher_create",
            {
                "project_id": "proj-1",
                "name": "My Launcher",
                "resource_class_id": 1,
                "environment": {
                    "environment_image_source": "image",
                    "container_image": "ubuntu:latest",
                    "environment_kind": "CUSTOM",
                },
            },
        )
        _, _, _, body = deps.api.call_args.args
        assert body["environment"]["name"] == "My Launcher"


@pytest.mark.asyncio
async def test_launcher_create_no_name_for_build(mock_deps):
    """launcher_create does NOT inject 'name' for build-source environments."""
    mock_deps.api.return_value = {"id": "launcher-1", "environment": {}}

    async with mcp_session(mock_deps) as (session, deps):
        await session.call_tool(
            "launcher_create",
            {
                "project_id": "proj-1",
                "name": "Build Launcher",
                "resource_class_id": 1,
                "environment": {
                    "environment_image_source": "build",
                    "repository": "https://github.com/x/y",
                    "builder_variant": "python",
                    "frontend_variant": "jupyter",
                },
            },
        )
        _, _, _, body = deps.api.call_args.args
        assert "name" not in body["environment"]
