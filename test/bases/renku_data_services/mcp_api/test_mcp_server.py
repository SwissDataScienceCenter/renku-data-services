"""Tests for the Renku MCP server."""

from __future__ import annotations

import asyncio
import datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest

from renku_data_services.mcp_api.client import RenkuApiClient
from renku_data_services.mcp_api.main import (
    TokenNotFoundError,
    _authorization_server_doc,
    _protected_resource_doc,
    _resolve_token,
)
from renku_data_services.mcp_api.server import (
    _admin_checked_token,
    _is_secret_key,
    _launcher_summary,
    _project_path,
    _secret_keys,
    _started_recently,
)
from test.bases.renku_data_services.mcp_api.conftest import (
    iso_ago,
    make_session,
    mcp_session,
    tool_result_dict,
)


@pytest.fixture(autouse=True)
def clear_admin_check():
    """Ensure a completed admin check doesn't bleed between tests."""
    _admin_checked_token.set("")
    yield
    _admin_checked_token.set("")


# ------------------------------------------------------------------ #
# Pure logic — no server needed                                        #
# ------------------------------------------------------------------ #


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
# Token resolution — stdio mode reads the environment only            #
# ------------------------------------------------------------------ #


@pytest.mark.parametrize("var", ["RENKU_ACCESS_TOKEN", "RENKU_TOKEN", "RENKU_CLI_ACCESS_TOKEN"])
def test_resolve_token_reads_each_env_var(var, monkeypatch):
    """Any of the three accepted variables supplies the token."""
    for name in ("RENKU_ACCESS_TOKEN", "RENKU_TOKEN", "RENKU_CLI_ACCESS_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(var, "env-token")
    assert _resolve_token() == "env-token"


def test_resolve_token_prefers_renku_access_token(monkeypatch):
    """RENKU_ACCESS_TOKEN wins when more than one variable is set."""
    monkeypatch.setenv("RENKU_ACCESS_TOKEN", "first")
    monkeypatch.setenv("RENKU_TOKEN", "second")
    monkeypatch.setenv("RENKU_CLI_ACCESS_TOKEN", "third")
    assert _resolve_token() == "first"


def test_resolve_token_forwards_any_token_value(monkeypatch):
    """Tokens are forwarded as-is without JWT validation — the data API validates."""
    for name in ("RENKU_TOKEN", "RENKU_CLI_ACCESS_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("RENKU_ACCESS_TOKEN", "opaque-or-expired-or-wrong-issuer")
    assert _resolve_token() == "opaque-or-expired-or-wrong-issuer"


def test_resolve_token_raises_when_env_is_empty(monkeypatch):
    """With nothing in the environment the error names the variables to set."""
    for name in ("RENKU_ACCESS_TOKEN", "RENKU_TOKEN", "RENKU_CLI_ACCESS_TOKEN"):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(TokenNotFoundError, match="RENKU_ACCESS_TOKEN"):
        _resolve_token()


# ------------------------------------------------------------------ #
# RenkuApiClient.request — test via pytest-httpx                       #
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_api_sets_auth_header(httpx_mock):
    httpx_mock.add_response(json={"ok": True})
    api = RenkuApiClient(base_url="https://test.renkulab.io")
    await api.request("GET", "/projects", "my-token")

    request = httpx_mock.get_request()
    assert request.headers["Authorization"] == "Bearer my-token"
    assert request.headers["Accept"] == "application/json"


@pytest.mark.asyncio
async def test_api_constructs_correct_url(httpx_mock):
    httpx_mock.add_response(json=[])
    api = RenkuApiClient(base_url="https://test.renkulab.io")
    await api.request("GET", "/projects", "tok", query={"namespace": "myuser"})

    request = httpx_mock.get_request()
    assert str(request.url).startswith("https://test.renkulab.io/api/data/projects")
    assert "namespace=myuser" in str(request.url)


@pytest.mark.asyncio
async def test_api_raises_on_http_error(httpx_mock):
    httpx_mock.add_response(status_code=403, text="Forbidden")
    api = RenkuApiClient(base_url="https://test.renkulab.io")

    with pytest.raises(RuntimeError, match="HTTP 403"):
        await api.request("GET", "/projects", "tok")


@pytest.mark.asyncio
async def test_api_returns_headers_when_requested(httpx_mock):
    httpx_mock.add_response(json={"id": "1"}, headers={"ETag": '"abc123"'})
    api = RenkuApiClient(base_url="https://test.renkulab.io")
    result, headers = await api.request("GET", "/projects/1", "tok", return_headers=True)

    assert result == {"id": "1"}
    assert "etag" in {k.lower() for k in headers}


# ------------------------------------------------------------------ #
# Admin check                                                          #
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_admin_blocks_tool_calls(mock_api):
    """All tools except auth_status are blocked for admin users."""

    async def fake_api(method: str, path: str, token: str, *args: Any, **kwargs: Any) -> Any:
        if path == "/user":
            return {"is_admin": True, "id": "admin"}
        return []

    mock_api.request.side_effect = fake_api

    async with mcp_session(mock_api) as (session, _):
        result = await session.call_tool("project_list", {})
        assert result.isError is True
        assert "admin" in result.content[0].text.lower()


@pytest.mark.asyncio
async def test_non_admin_allowed(mock_api):
    """Non-admin users can call tools normally."""

    async def fake_api(method: str, path: str, token: str, *args: Any, **kwargs: Any) -> Any:
        if path == "/user":
            return {"is_admin": False, "id": "user1"}
        return []

    mock_api.request.side_effect = fake_api

    async with mcp_session(mock_api) as (session, _):
        result = await session.call_tool("project_list", {})
        assert result.isError is not True


@pytest.mark.asyncio
async def test_admin_rechecked_each_tool_call(mock_api):
    """Admin status is re-checked on each tool call — it is not cached for the process."""

    async def fake_api(method: str, path: str, token: str, *args: Any, **kwargs: Any) -> Any:
        if path == "/user":
            return {"is_admin": False, "id": "user1"}
        return []

    mock_api.request.side_effect = fake_api

    async with mcp_session(mock_api) as (session, _):
        await session.call_tool("project_list", {})
        await session.call_tool("session_list", {})

    user_calls = [c for c in mock_api.request.call_args_list if c.args[1] == "/user"]
    assert len(user_calls) == 2


@pytest.mark.asyncio
async def test_admin_checked_once_while_polling(mock_api, monkeypatch):
    """A wait loop polls repeatedly but checks admin status only once.

    This is what the per-context scoping buys: session_wait can poll ~90 times
    on its defaults, and re-checking on every poll would double its load.
    """
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())
    states = iter(["starting", "starting", "running"])

    async def fake_api(method: str, path: str, token: str, *args: Any, **kwargs: Any) -> Any:
        if path == "/user":
            return {"is_admin": False, "id": "user1"}
        if path == "/sessions/s1":
            return make_session(next(states, "running"))
        return []

    mock_api.request.side_effect = fake_api

    async with mcp_session(mock_api) as (session, _):
        await session.call_tool("session_wait", {"session_id": "s1", "interval": 1})

    user_calls = [c for c in mock_api.request.call_args_list if c.args[1] == "/user"]
    session_calls = [c for c in mock_api.request.call_args_list if c.args[1] == "/sessions/s1"]
    assert len(session_calls) == 3, "expected the loop to poll until the session was running"
    assert len(user_calls) == 1


@pytest.mark.asyncio
async def test_admin_override_env(mock_api, monkeypatch):
    """RENKU_MCP_ALLOW_ADMIN=1 lets admin users through."""
    monkeypatch.setenv("RENKU_MCP_ALLOW_ADMIN", "1")

    async def fake_api(method: str, path: str, token: str, *args: Any, **kwargs: Any) -> Any:
        if path == "/user":
            return {"is_admin": True, "id": "admin"}
        return []

    mock_api.request.side_effect = fake_api

    async with mcp_session(mock_api) as (session, _):
        result = await session.call_tool("project_list", {})
        assert result.isError is not True


# ------------------------------------------------------------------ #
# Tool behaviour — in-process MCP + mocked deps                       #
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_list_tools_smoke(mock_api):
    """Server exposes the expected core tools."""
    async with mcp_session(mock_api) as (session, _):
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
            "app_launch",
            "app_list",
            "app_get",
            "app_logs",
            "app_delete",
            "app_wait",
        ):
            assert expected in names, f"Missing tool: {expected}"


@pytest.mark.asyncio
async def test_job_run_marks_new_session(mock_api):
    """job_run sets _created=True when started_at is recent."""
    non_interactive_launcher = {"id": "launcher-1", "launcher_type": "non_interactive"}

    async def fake_api(method: str, path: str, token: str, *args: Any, **kwargs: Any) -> Any:
        if path == "/user":
            return {"is_admin": False}
        if method == "GET" and "session_launchers" in path:
            return non_interactive_launcher
        return make_session("running", started_at=iso_ago(5))

    mock_api.request.side_effect = fake_api

    async with mcp_session(mock_api) as (session, _):
        result = await session.call_tool("job_run", {"launcher_id": "launcher-1"})
        data = tool_result_dict(result)
        assert data["_created"] is True


@pytest.mark.asyncio
async def test_job_run_marks_stale_session(mock_api):
    """job_run sets _created=False when the platform returned a pre-existing session."""
    non_interactive_launcher = {"id": "launcher-1", "launcher_type": "non_interactive"}

    async def fake_api(method: str, path: str, token: str, *args: Any, **kwargs: Any) -> Any:
        if path == "/user":
            return {"is_admin": False}
        if method == "GET" and "session_launchers" in path:
            return non_interactive_launcher
        return make_session("running", started_at=iso_ago(300))

    mock_api.request.side_effect = fake_api

    async with mcp_session(mock_api) as (session, _):
        result = await session.call_tool("job_run", {"launcher_id": "launcher-1"})
        data = tool_result_dict(result)
        assert data["_created"] is False


@pytest.mark.asyncio
async def test_session_delete_if_failed_deletes_terminal_states(mock_api):
    """session_delete_if_failed deletes sessions in any terminal state."""
    async with mcp_session(mock_api) as (session, api):
        for state in ("failed", "error", "stopped", "succeeded", "completed", "finished"):
            api.request.reset_mock()
            api.request.return_value = make_session(state)
            result = await session.call_tool("session_delete_if_failed", {"session_id": "s1"})
            assert "Deleted" in result.content[0].text, f"Expected deletion for state '{state}'"
            paths = [c.args[1] for c in api.request.call_args_list]
            assert "/sessions/s1" in paths, f"Expected GET /sessions/s1 for state '{state}'"
            methods = [c.args[0] for c in api.request.call_args_list if c.args[1] == "/sessions/s1"]
            assert "DELETE" in methods, f"Expected DELETE for state '{state}'"


@pytest.mark.asyncio
async def test_session_delete_if_failed_skips_running(mock_api):
    """session_delete_if_failed does not delete running sessions."""
    mock_api.request.return_value = make_session("running")

    async with mcp_session(mock_api) as (session, api):
        result = await session.call_tool("session_delete_if_failed", {"session_id": "s1"})
        assert "not deleted" in result.content[0].text
        methods = [c.args[0] for c in api.request.call_args_list if c.args[1] == "/sessions/s1"]
        assert "GET" in methods
        assert "DELETE" not in methods


@pytest.mark.asyncio
async def test_job_wait_returns_timed_out_flag(mock_api):
    """job_wait returns timed_out=True instead of raising when it times out."""

    async def fake_api(method: str, path: str, token: str, *args: Any, **kwargs: Any) -> Any:
        if path == "/user":
            return {"is_admin": False}
        if "/logs" in path:
            return {}
        return make_session("starting")

    mock_api.request.side_effect = fake_api

    async with mcp_session(mock_api) as (session, _):
        result = await session.call_tool("job_wait", {"session_id": "s1", "timeout": 1, "interval": 1})
        data = tool_result_dict(result)
        assert data["timed_out"] is True
        assert "state" in data


@pytest.mark.asyncio
async def test_project_create_sends_correct_body(mock_api):
    """project_create passes name, namespace, and visibility to the API."""
    mock_api.request.return_value = {"id": "new-proj", "name": "My Project"}

    async with mcp_session(mock_api) as (session, api):
        await session.call_tool(
            "project_create",
            {"name": "My Project", "namespace": "myuser", "visibility": "public"},
        )
        post_calls = [c for c in api.request.call_args_list if c.args[0] == "POST"]
        assert len(post_calls) == 1
        _, path, _, body = post_calls[0].args
        assert path == "/projects"
        assert body["name"] == "My Project"
        assert body["namespace"] == "myuser"
        assert body["visibility"] == "public"


@pytest.mark.asyncio
async def test_project_repo_add_sends_etag(mock_api):
    """project_repo_add fetches the ETag and passes it as If-Match on the PATCH."""
    project = {"id": "proj-1", "etag": '"v1"', "repositories": []}

    async def fake_api(method: str, path: str, token: str, body: Any = None, **kwargs: Any) -> Any:
        if path == "/user":
            return {"is_admin": False}
        if method == "GET" and kwargs.get("return_headers"):
            return project, {"ETag": '"v1"'}
        return {"id": "proj-1", "repositories": ["https://github.com/x/y"]}

    mock_api.request.side_effect = fake_api

    async with mcp_session(mock_api) as (session, api):
        await session.call_tool("project_repo_add", {"project": "proj-1", "repository_url": "https://github.com/x/y"})

    patch_calls = [c for c in api.request.call_args_list if c.args[0] == "PATCH"]
    assert len(patch_calls) == 1
    assert patch_calls[0].kwargs.get("extra_headers", {}).get("If-Match") == '"v1"'


@pytest.mark.asyncio
async def test_project_repo_add_raises_without_etag(mock_api):
    """project_repo_add raises when the project has no ETag."""

    async def fake_api(method: str, path: str, token: str, *args: Any, **kwargs: Any) -> Any:
        if path == "/user":
            return {"is_admin": False}
        return {"id": "proj-1", "repositories": []}  # no etag field

    mock_api.request.side_effect = fake_api

    async with mcp_session(mock_api) as (session, _):
        result = await session.call_tool(
            "project_repo_add", {"project": "proj-1", "repository_url": "https://github.com/x/y"}
        )
        assert result.isError is True


@pytest.mark.asyncio
async def test_launcher_create_injects_name_for_image(mock_api):
    """launcher_create adds 'name' to the environment dict for image-source environments."""
    mock_api.request.return_value = {"id": "launcher-1", "environment": {}}

    async with mcp_session(mock_api) as (session, api):
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
        _, _, _, body = api.request.call_args.args
        assert body["environment"]["name"] == "My Launcher"


@pytest.mark.asyncio
async def test_launcher_create_no_name_for_build(mock_api):
    """launcher_create does NOT inject 'name' for build-source environments."""
    mock_api.request.return_value = {"id": "launcher-1", "environment": {}}

    async with mcp_session(mock_api) as (session, api):
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
        _, _, _, body = api.request.call_args.args
        assert "name" not in body["environment"]


# ------------------------------------------------------------------ #
# Apps                                                                 #
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_app_launch_sends_only_launcher_id(mock_api):
    """POST /apps takes just the launcher_id — the platform names the app itself."""
    mock_api.request.return_value = {"name": "my-app-0h8kq2zt", "status": "pending"}

    async with mcp_session(mock_api) as (session, api):
        result = await session.call_tool("app_launch", {"launcher_id": "launcher-1"})

        method, path, _, body = api.request.call_args.args
        assert (method, path) == ("POST", "/apps")
        assert body == {"launcher_id": "launcher-1"}
        assert tool_result_dict(result)["name"] == "my-app-0h8kq2zt"


@pytest.mark.asyncio
async def test_app_list_filters_by_project(mock_api):
    """app_list passes project_id as a query parameter, not a path segment."""

    async def fake_api(method: str, path: str, token: str, *args: Any, **kwargs: Any) -> Any:
        return {"is_admin": False} if path == "/user" else []

    mock_api.request.side_effect = fake_api

    async with mcp_session(mock_api) as (session, api):
        await session.call_tool("app_list", {"project_id": "proj-1"})

        method, path, *_ = api.request.call_args.args
        assert (method, path) == ("GET", "/apps")
        assert api.request.call_args.kwargs["query"] == {"project_id": "proj-1"}


@pytest.mark.asyncio
async def test_app_logs_omits_max_lines_when_unset(mock_api):
    """No max_lines means no query parameter, so the API applies its own default."""
    mock_api.request.return_value = {}

    async with mcp_session(mock_api) as (session, api):
        await session.call_tool("app_logs", {"app_name": "my-app"})
        assert api.request.call_args.kwargs["query"] is None

        await session.call_tool("app_logs", {"app_name": "my-app", "max_lines": 50})
        assert api.request.call_args.kwargs["query"] == {"max_lines": 50}


@pytest.mark.asyncio
async def test_app_wait_returns_when_ready(mock_api, monkeypatch):
    """app_wait polls until the app is ready and reports timed_out=False."""
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())
    statuses = iter(["pending", "pending", "ready"])

    async def fake_api(method: str, path: str, token: str, *args: Any, **kwargs: Any) -> Any:
        if path == "/user":
            return {"is_admin": False}
        return {"name": "my-app", "status": next(statuses, "ready")}

    mock_api.request.side_effect = fake_api

    async with mcp_session(mock_api) as (session, _):
        result = await session.call_tool("app_wait", {"app_name": "my-app", "interval": 1})

    payload = tool_result_dict(result)
    assert payload["status"] == "ready"
    assert payload["timed_out"] is False


@pytest.mark.asyncio
async def test_app_wait_attaches_logs_on_failure(mock_api, monkeypatch):
    """A failed app comes back with its logs, so the agent can explain the failure."""
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())

    async def fake_api(method: str, path: str, token: str, *args: Any, **kwargs: Any) -> Any:
        if path == "/user":
            return {"is_admin": False}
        if path.endswith("/logs"):
            return {"my-app-pod-1/app": "Traceback: boom"}
        return {"name": "my-app", "status": "failed"}

    mock_api.request.side_effect = fake_api

    async with mcp_session(mock_api) as (session, _):
        result = await session.call_tool("app_wait", {"app_name": "my-app"})

    payload = tool_result_dict(result)
    assert payload["status"] == "failed"
    assert payload["logs"] == {"my-app-pod-1/app": "Traceback: boom"}


@pytest.mark.asyncio
async def test_app_wait_times_out(mock_api, monkeypatch):
    """A never-ready app reports timed_out=True rather than hanging or claiming success."""
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())
    mock_api.request.return_value = {"name": "my-app", "status": "pending"}

    async with mcp_session(mock_api) as (session, _):
        result = await session.call_tool("app_wait", {"app_name": "my-app", "timeout": 1})

    payload = tool_result_dict(result)
    assert payload["timed_out"] is True
    assert payload["status"] == "pending"


@pytest.mark.asyncio
async def test_app_delete_confirms_by_name(mock_api):
    """app_delete issues a DELETE and reports which app went away."""

    async def fake_api(method: str, path: str, token: str, *args: Any, **kwargs: Any) -> Any:
        return {"is_admin": False} if path == "/user" else None

    mock_api.request.side_effect = fake_api

    async with mcp_session(mock_api) as (session, api):
        result = await session.call_tool("app_delete", {"app_name": "my-app", "confirm": True})

        method, path, *_ = api.request.call_args.args
        assert (method, path) == ("DELETE", "/apps/my-app")
        assert "my-app" in result.content[0].text


@pytest.mark.asyncio
async def test_launcher_create_hyphenates_launcher_type(mock_api):
    """The API enum is hyphenated, so an underscored launcher_type must be normalised."""
    mock_api.request.return_value = {"id": "launcher-1", "environment": {}}

    async with mcp_session(mock_api) as (session, api):
        await session.call_tool(
            "launcher_create",
            {
                "project_id": "proj-1",
                "name": "Job Launcher",
                "resource_class_id": 1,
                "environment": {"id": "env-1"},
                "launcher_type": "non_interactive",
            },
        )
        _, _, _, body = api.request.call_args.args
        assert body["launcher_type"] == "non-interactive"


@pytest.mark.asyncio
async def test_launcher_create_omits_launcher_type_when_unset(mock_api):
    """Interactive launchers send no launcher_type at all — older deployments reject it."""
    mock_api.request.return_value = {"id": "launcher-1", "environment": {}}

    async with mcp_session(mock_api) as (session, api):
        await session.call_tool(
            "launcher_create",
            {
                "project_id": "proj-1",
                "name": "Session Launcher",
                "resource_class_id": 1,
                "environment": {"id": "env-1"},
            },
        )
        _, _, _, body = api.request.call_args.args
        assert "launcher_type" not in body


# ------------------------------------------------------------------ #
# Guardrails enforced in code                                          #
# ------------------------------------------------------------------ #


class TestSecretDetection:
    @pytest.mark.parametrize(
        "key",
        ["password", "pass", "secret_access_key", "access_key_id", "sas_url", "username", "key_pem", "KEY"],
    )
    def test_flags_credential_keys(self, key):
        assert _secret_keys({"configuration": {key: "hunter2"}}) == [f"configuration.{key}"]

    @pytest.mark.parametrize("key", ["key_file", "public_url", "source_path", "provider", "endpoint", "readonly"])
    def test_allows_locations_and_flags(self, key):
        assert _secret_keys({"configuration": {key: "value"}}) == []

    def test_ignores_empty_values(self):
        """An empty secret field is a placeholder the user will fill in, not a leaked credential."""
        assert _secret_keys({"configuration": {"password": ""}}) == []

    def test_finds_nested_and_listed(self):
        found = _secret_keys({"a": [{"b": {"secret": "x"}}]})
        assert found == ["a[0].b.secret"]


@pytest.mark.asyncio
async def test_connector_create_refuses_credentials(mock_api):
    """A credential in the storage config is refused before any HTTP call is made."""

    async def fake_api(method: str, path: str, token: str, *args: Any, **kwargs: Any) -> Any:
        return {"is_admin": False} if path == "/user" else {"id": "dc-1"}

    mock_api.request.side_effect = fake_api

    async with mcp_session(mock_api) as (session, api):
        result = await session.call_tool(
            "connector_create",
            {
                "name": "my-s3",
                "namespace": "myuser",
                "project_id": "proj-1",
                "storage": {"configuration": {"type": "s3", "secret_access_key": "AKIAsecret"}},
            },
        )

    assert result.isError is True
    text = result.content[0].text
    assert "secret_access_key" in text
    assert "AKIAsecret" not in text, "the refusal must not echo the credential back"
    posts = [c for c in api.request.call_args_list if c.args[0] == "POST"]
    assert posts == [], "nothing should reach the API when credentials are present"


@pytest.mark.asyncio
async def test_connector_patch_refuses_credentials(mock_api):
    async def fake_api(method: str, path: str, token: str, *args: Any, **kwargs: Any) -> Any:
        return {"is_admin": False} if path == "/user" else {}

    mock_api.request.side_effect = fake_api

    async with mcp_session(mock_api) as (session, api):
        result = await session.call_tool(
            "connector_patch",
            {"connector_id": "dc-1", "body": {"storage": {"configuration": {"password": "hunter2"}}}},
        )

    assert result.isError is True
    assert [c for c in api.request.call_args_list if c.args[0] == "PATCH"] == []


@pytest.mark.asyncio
async def test_destructive_tool_refuses_without_confirmation(mock_api):
    """The in-process test client declares no elicitation capability, so deletion is refused."""

    async def fake_api(method: str, path: str, token: str, *args: Any, **kwargs: Any) -> Any:
        return {"is_admin": False} if path == "/user" else {}

    mock_api.request.side_effect = fake_api

    async with mcp_session(mock_api) as (session, api):
        result = await session.call_tool("app_delete", {"app_name": "my-app"})

    assert result.isError is True
    assert "confirm" in result.content[0].text.lower()
    assert [c for c in api.request.call_args_list if c.args[0] == "DELETE"] == []


@pytest.mark.asyncio
async def test_destructive_tool_proceeds_when_confirmed(mock_api):
    """confirm=true is the fallback path for clients that cannot be asked."""

    async def fake_api(method: str, path: str, token: str, *args: Any, **kwargs: Any) -> Any:
        return {"is_admin": False} if path == "/user" else None

    mock_api.request.side_effect = fake_api

    async with mcp_session(mock_api) as (session, api):
        result = await session.call_tool("app_delete", {"app_name": "my-app", "confirm": True})

    assert result.isError is not True
    deletes = [c for c in api.request.call_args_list if c.args[0] == "DELETE"]
    assert [c.args[1] for c in deletes] == ["/apps/my-app"]


@pytest.mark.asyncio
async def test_session_delete_if_failed_needs_no_confirmation(mock_api):
    """A terminal session has nothing left to lose, so cleanup is not gated."""

    async def fake_api(method: str, path: str, token: str, *args: Any, **kwargs: Any) -> Any:
        if path == "/user":
            return {"is_admin": False}
        return make_session("failed")

    mock_api.request.side_effect = fake_api

    async with mcp_session(mock_api) as (session, api):
        result = await session.call_tool("session_delete_if_failed", {"session_id": "s1"})

    assert result.isError is not True
    assert [c for c in api.request.call_args_list if c.args[0] == "DELETE"] != []


@pytest.mark.asyncio
async def test_connector_create_unlinked_requires_confirmation(mock_api):
    """Creating a connector with no project link asks first, rather than silently orphaning it."""

    async def fake_api(method: str, path: str, token: str, *args: Any, **kwargs: Any) -> Any:
        return {"is_admin": False} if path == "/user" else {"id": "dc-1"}

    mock_api.request.side_effect = fake_api

    async with mcp_session(mock_api) as (session, api):
        result = await session.call_tool(
            "connector_create",
            {"name": "my-s3", "namespace": "myuser", "storage": {"configuration": {"type": "s3"}}},
        )

    assert result.isError is True
    assert [c for c in api.request.call_args_list if c.args[0] == "POST"] == []


def test_secret_field_list_matches_rclone_schema():
    """The checked-in secret list must cover every option rclone marks sensitive.

    _RCLONE_SECRET_OPTIONS is a copy, taken so the MCP server need not import the storage
    component at runtime. This test is what keeps the copy honest: if rclone gains a
    sensitive option, it fails and names it.
    """
    from renku_data_services.storage.rclone import RCloneValidator

    validator = RCloneValidator()
    sensitive = {
        option.name
        for provider in validator.providers.values()
        for option in provider.options
        if getattr(option, "sensitive", False)
    }
    missing = sorted(name for name in sensitive if not _is_secret_key(name))
    assert not missing, f"rclone marks these sensitive but the MCP server would not refuse them: {missing}"


@pytest.mark.asyncio
async def test_destructive_tool_asks_the_user_and_proceeds(mock_api):
    """With an elicitation-capable client the server asks, and a yes lets the delete through."""

    async def fake_api(method: str, path: str, token: str, *args: Any, **kwargs: Any) -> Any:
        return {"is_admin": False} if path == "/user" else None

    mock_api.request.side_effect = fake_api

    async with mcp_session(mock_api, elicit=True) as (session, api):
        result = await session.call_tool("app_delete", {"app_name": "my-app"})

    assert result.isError is not True
    assert [c.args[1] for c in api.request.call_args_list if c.args[0] == "DELETE"] == ["/apps/my-app"]


@pytest.mark.asyncio
async def test_destructive_tool_stops_when_user_says_no(mock_api):
    """A 'no' answer stops the deletion — the agent cannot talk its way past this."""

    async def fake_api(method: str, path: str, token: str, *args: Any, **kwargs: Any) -> Any:
        return {"is_admin": False} if path == "/user" else None

    mock_api.request.side_effect = fake_api

    async with mcp_session(mock_api, elicit=False) as (session, api):
        result = await session.call_tool("app_delete", {"app_name": "my-app"})

    assert result.isError is True
    assert "did not agree" in result.content[0].text
    assert [c for c in api.request.call_args_list if c.args[0] == "DELETE"] == []


@pytest.mark.asyncio
async def test_destructive_tool_stops_when_user_declines(mock_api):
    """A declined prompt is refused too, not treated as consent."""

    async def fake_api(method: str, path: str, token: str, *args: Any, **kwargs: Any) -> Any:
        return {"is_admin": False} if path == "/user" else None

    mock_api.request.side_effect = fake_api

    async with mcp_session(mock_api, elicit=None) as (session, api):
        result = await session.call_tool("session_delete", {"session_id": "s1"})

    assert result.isError is True
    assert [c for c in api.request.call_args_list if c.args[0] == "DELETE"] == []


@pytest.mark.asyncio
async def test_unlinked_connector_created_after_user_agrees(mock_api):
    """The orphan warning is a question, not a block — the user can say yes."""

    async def fake_api(method: str, path: str, token: str, *args: Any, **kwargs: Any) -> Any:
        return {"is_admin": False} if path == "/user" else {"id": "dc-1"}

    mock_api.request.side_effect = fake_api

    async with mcp_session(mock_api, elicit=True) as (session, api):
        result = await session.call_tool(
            "connector_create",
            {"name": "my-s3", "namespace": "myuser", "storage": {"configuration": {"type": "s3"}}},
        )

    assert result.isError is not True
    assert [c.args[1] for c in api.request.call_args_list if c.args[0] == "POST"] == ["/data_connectors"]


class TestStartedRecently:
    """job_run infers whether a session is new from its start time — these are the edge cases."""

    def test_just_started_is_new(self):
        assert _started_recently({"started_at": iso_ago(2)}) is True

    def test_long_running_is_pre_existing(self):
        assert _started_recently({"started_at": iso_ago(3600)}) is False

    def test_reads_nested_status(self):
        assert _started_recently({"status": {"started_at": iso_ago(3600)}}) is False

    def test_accepts_zulu_suffix(self):
        """fromisoformat handles 'Z' natively on the Python this runs on."""
        stamp = datetime.datetime.now(datetime.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        assert _started_recently({"started_at": stamp}) is True

    def test_assumes_utc_for_naive_timestamps(self):
        naive = (datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=1)).replace(tzinfo=None).isoformat()
        assert _started_recently({"started_at": naive}) is False

    @pytest.mark.parametrize("value", [None, "", "not-a-timestamp", 12345, {}])
    def test_unusable_timestamp_counts_as_new(self, value):
        """Better to treat an unknown session as new than to have the agent delete it."""
        assert _started_recently({"started_at": value}) is True
