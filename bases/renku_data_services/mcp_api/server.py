"""FastMCP server — all tools call the Renku REST API."""

from __future__ import annotations

import contextvars
import datetime
import time
from contextlib import asynccontextmanager
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.server import Context
from pydantic import Field

from renku_data_services.mcp_api.dependencies import MCPDependencies

# Current request token — set by ASGI auth middleware (HTTP) or main.py at startup (stdio).
_current_token: contextvars.ContextVar[str] = contextvars.ContextVar("mcp_token", default="")


def set_current_token(token: str) -> contextvars.Token[str]:
    return _current_token.set(token)


def _token(ctx: Context) -> str:
    t = _current_token.get()
    if t:
        return t
    return ctx.request_context.lifespan_context.get("token", "")


def _deps(ctx: Context) -> MCPDependencies:
    return ctx.request_context.lifespan_context["deps"]


# Cache admin status per token so we only call /user once per session/request.
_admin_cache: dict[str, bool] = {}


async def _require_non_admin(ctx: Context) -> None:
    """Raise if the current user is a Renku admin.

    Admin accounts have platform-wide write access that bypasses normal
    permission checks — running agent operations as an admin is dangerous.
    Set RENKU_MCP_ALLOW_ADMIN=1 in the server environment to override.
    """
    import os
    if os.environ.get("RENKU_MCP_ALLOW_ADMIN"):
        return
    t = _token(ctx)
    if not t:
        return
    if t not in _admin_cache:
        try:
            user = await _deps(ctx).api("GET", "/user", t)
            _admin_cache[t] = bool(user.get("is_admin", False))
        except Exception:
            return  # can't check — don't block, let the API enforce its own authz
    if _admin_cache.get(t):
        raise RuntimeError(
            "Refusing to operate as a Renku admin. "
            "Log out and log back in as a non-admin account, "
            "or set RENKU_MCP_ALLOW_ADMIN=1 to override."
        )


async def _api(ctx: Context, method: str, path: str, body: Any = None, **kwargs: Any) -> Any:
    """Make an authenticated API call, refusing if the current user is an admin."""
    await _require_non_admin(ctx)
    return await _deps(ctx).api(method, path, _token(ctx), body, **kwargs)


def _is_stale_session(s: dict[str, Any]) -> bool:
    """True if a session has a will_delete_at timestamp already in the past."""
    wda = s.get("will_delete_at")
    if not wda:
        return False
    try:
        ts = datetime.datetime.fromisoformat(wda.replace("Z", "+00:00")).timestamp()
        return ts < time.time()
    except Exception:
        return False


def _launcher_summary(data: dict[str, Any]) -> dict[str, Any]:
    """Attach a concise _handoff block to a launcher response for easy downstream use."""
    env = data.get("environment") or {}
    data["_handoff"] = {
        "launcher_id": data.get("id"),
        "environment_id": env.get("id"),
        "resource_class_id": data.get("resource_class_id"),
        "container_image": env.get("container_image"),
        "port": env.get("port"),
        "command": env.get("command"),
        "args": env.get("args"),
    }
    return data


def _project_path(ident: str) -> str:
    """Turn a project ID or namespace/slug into an API path segment."""
    import urllib.parse

    if "/" in ident:
        ns, slug = ident.split("/", 1)
        return f"/namespaces/{urllib.parse.quote(ns, safe='')}/projects/{urllib.parse.quote(slug, safe='')}"
    return f"/projects/{urllib.parse.quote(ident, safe='')}"


def create_server(deps: MCPDependencies) -> FastMCP:
    """Create and return the configured FastMCP server."""

    @asynccontextmanager
    async def lifespan(server: FastMCP):  # type: ignore[type-arg]
        yield {"deps": deps, "token": _current_token.get()}

    mcp = FastMCP(
        "Renku",
        lifespan=lifespan,
        instructions=(
            "Tools for the Renku data science platform.\n\n"
            "Safety rules:\n"
            "- If auth_status shows is_admin=true, do not perform any operation. "
            "Ask the user to log out and log back in as a non-admin.\n"
            "- Always call resource_classes(cpu=..., memory=..., gpu=...) before creating a launcher "
            "or running a job, passing your requirements so matching=true is set correctly. "
            "Pick the smallest class where matching=true and pass its id.\n"
            "- Always pass project_id to connector_create so the connector is linked immediately. "
            "A connector created without project_id is orphaned — not visible in any project.\n"
            "- Never include credentials in connector storage configurations. "
            "Direct the user to add secrets through the Renku UI after creation.\n"
            "- Confirm with the user before deleting connectors, launchers, or running sessions.\n"
            "- Never ask for storage credentials (S3 keys, passwords). "
            "Direct the user to add them through the Renku UI.\n"
            "- Never sleep or poll manually while waiting for sessions, jobs, or builds. "
            "Always use session_wait(), job_wait(), or build_wait() instead.\n\n"
            "Session URLs:\n"
            "Always construct session UI URLs as "
            "{base_url}/p/<namespace>/<project-slug>/sessions/show/<session-name>. "
            "Do NOT use the url field from the session API response — it returns an internal path, "
            "not the correct UI URL."
        ),
    )

    # ------------------------------------------------------------------ #
    # Auth / platform                                                      #
    # ------------------------------------------------------------------ #

    @mcp.tool()
    async def auth_status(ctx: Context) -> dict[str, Any]:
        """Return current authentication status and user info.
        Always call this first; refuse all operations if is_admin is true."""
        t = _token(ctx)
        if not t:
            return {
                "authenticated": False,
                "base_url": _deps(ctx).base_url,
                "hint": "Set RENKU_ACCESS_TOKEN in the MCP server environment, or run 'rnk login'.",
            }
        try:
            user = await _deps(ctx).api("GET", "/user", t)
            return {
                "authenticated": True,
                "base_url": _deps(ctx).base_url,
                "user": user,
                "is_admin": user.get("is_admin", False),
            }
        except RuntimeError as exc:
            return {"authenticated": False, "base_url": _deps(ctx).base_url, "error": str(exc)}

    @mcp.tool()
    async def resource_classes(
        ctx: Context,
        cpu: Annotated[float | None, Field(description="Minimum CPU cores required", ge=0)] = None,
        memory: Annotated[int | None, Field(description="Minimum memory in GB required", ge=0)] = None,
        gpu: Annotated[int | None, Field(description="Minimum GPUs required", ge=0)] = None,
        max_storage: Annotated[int | None, Field(description="Minimum storage in GB required", ge=0)] = None,
    ) -> list[dict[str, Any]]:
        """List available compute resource classes.
        Always call this before creating a launcher or running a job.
        Pass your resource requirements so the API can set matching=true on
        suitable classes. Pick the smallest class where matching=true."""
        query = {k: v for k, v in {"cpu": cpu, "memory": memory, "gpu": gpu, "max_storage": max_storage}.items() if v is not None}
        pools = await _api(ctx, "GET", "/resource_pools", query=query or None)
        classes: list[dict[str, Any]] = []
        for pool in pools if isinstance(pools, list) else pools.get("resource_pools", []):
            for cls in pool.get("classes", []):
                cls = dict(cls)
                cls["pool_name"] = pool.get("name")
                classes.append(cls)
        return classes

    @mcp.tool()
    async def namespaces(ctx: Context) -> list[dict[str, Any]]:
        """List namespaces accessible to the current user (personal namespace + groups)."""
        return await _api(ctx, "GET", "/namespaces")

    @mcp.tool()
    async def global_environments(ctx: Context) -> list[dict[str, Any]]:
        """List global session environments provided by the platform.
        Use these when the user has no container image and no repository to build from.
        Present the list to the user and let them pick one, then pass its id as the
        environment when calling launcher_create."""
        return await _api(ctx, "GET", "/environments")

    # ------------------------------------------------------------------ #
    # Projects                                                             #
    # ------------------------------------------------------------------ #

    @mcp.tool()
    async def project_list(
        ctx: Context,
        namespace: Annotated[str | None, Field(description="Filter by namespace slug")] = None,
    ) -> list[dict[str, Any]]:
        """List Renku projects accessible to the authenticated user."""
        query = {"namespace": namespace} if namespace else None
        return await _api(ctx, "GET", "/projects", query=query)

    @mcp.tool()
    async def project_get(
        ctx: Context,
        project: Annotated[str, Field(description="Project ID or namespace/slug (e.g. 'myuser/my-project')")],
    ) -> dict[str, Any]:
        """Get a Renku project by ID or namespace/slug."""
        return await _api(ctx, "GET", _project_path(project), _token(ctx))

    @mcp.tool()
    async def project_create(
        ctx: Context,
        name: Annotated[str, Field(description="Human-readable project name")],
        namespace: Annotated[str, Field(description="Namespace slug (from namespaces())")],
        visibility: Annotated[str, Field(description="'public' or 'private'")] = "private",
        description: Annotated[str, Field(description="Optional description")] = "",
        repository_url: Annotated[str, Field(description="Optional Git repository URL to attach")] = "",
    ) -> dict[str, Any]:
        """Create a new Renku project.
        Call namespaces() first to get the correct namespace slug. If the user already has a repository
        they want to add, add it here instead of with project_repo_add to do it all in one call."""
        body: dict[str, Any] = {"name": name, "namespace": namespace, "visibility": visibility}
        if description:
            body["description"] = description
        if repository_url:
            body["repositories"] = [repository_url]
        return await _api(ctx, "POST", "/projects", body)

    @mcp.tool()
    async def project_delete(
        ctx: Context,
        project: Annotated[str, Field(description="Project ID or namespace/slug")],
    ) -> str:
        """Delete a Renku project. Irreversible — confirm with the user before calling.

        Before deleting, call session_list(project_id=<id>) for both session types and
        job_list(project_id=<id>). Then:
        - Inform the user about the running sessions and pending jobs that will be stopped, and ask for
          explicit confirmation before proceeding.
        - Running or pending sessions: stop them with session_delete.
        - Hibernated or paused sessions: warn the user that unsaved work inside those
          sessions will be lost, and ask for explicit confirmation before stopping them."""
        proj = await _api(ctx, "GET", _project_path(project), _token(ctx))
        await _api(ctx, "DELETE", f"/projects/{proj['id']}")
        return f"Deleted project {proj['id']} ({proj.get('name', '')})"

    @mcp.tool()
    async def project_repo_add(
        ctx: Context,
        project: Annotated[str, Field(description="Project ID or namespace/slug")],
        repository_url: Annotated[str, Field(description="Git URL to add")],
    ) -> dict[str, Any]:
        """Add a Git repository URL to a project's repositories list."""
        proj, resp_headers = await _api(ctx, "GET", _project_path(project), return_headers=True)
        etag = resp_headers.get("ETag") or resp_headers.get("etag") or proj.get("etag")
        if not etag:
            raise RuntimeError("Could not get project ETag — cannot PATCH safely")
        repos = list(proj.get("repositories") or [])
        if repository_url not in repos:
            repos.append(repository_url)
        return await _api(
            ctx, "PATCH", f"/projects/{proj['id']}",
            {"repositories": repos},
            extra_headers={"If-Match": etag},
        )

    # ------------------------------------------------------------------ #
    # Data connectors                                                      #
    # ------------------------------------------------------------------ #

    @mcp.tool()
    async def connector_list(
        ctx: Context,
        namespace: Annotated[str, Field(description="Filter by namespace slug")] = "",
    ) -> list[dict[str, Any]]:
        """List data connectors visible to the current user, optionally filtered by namespace."""
        query = {"namespace": namespace} if namespace else None
        return await _api(ctx, "GET", "/data_connectors", query=query)

    @mcp.tool()
    async def connector_get(
        ctx: Context,
        connector_id: Annotated[str, Field(description="Connector ID")],
    ) -> dict[str, Any]:
        """Get a data connector by ID."""
        return await _api(ctx, "GET", f"/data_connectors/{connector_id}")

    @mcp.tool()
    async def connector_create(
        ctx: Context,
        storage: Annotated[dict[str, Any], Field(description="Storage configuration dict")],
        name: Annotated[str | None, Field(description="Connector display name (required for namespaced connectors)")] = None,
        namespace: Annotated[str | None, Field(description="Namespace slug (required for namespaced connectors)")] = None,
        visibility: Annotated[str, Field(description="'public' or 'private'")] = "public",
        project_id: Annotated[str, Field(description="Link to this project immediately (recommended)")] = "",
    ) -> dict[str, Any]:
        """Create a data connector for any storage backend (S3, WebDAV, SFTP, SMB, DOI, Polybox, etc.).

        For DOI/Zenodo connectors (global, no ownership), omit name and namespace:
          storage={"configuration": {"type": "doi", "doi": "10.5281/zenodo.123"}, "source_path": "/", "readonly": true}

        For all other backends, provide name and namespace. Storage examples:
          S3:      {"configuration": {"type": "s3", "provider": "Other", "endpoint": "https://..."}, "source_path": "/bucket", "target_path": "data", "readonly": true}
          WebDAV:  {"configuration": {"type": "webdav", "url": "https://..."}, "source_path": "/", "target_path": "data", "readonly": true}
          SFTP:    {"configuration": {"type": "sftp", "host": "..."}, "source_path": "/path", "target_path": "data", "readonly": true}
          Polybox: {"configuration": {"type": "polybox", "provider": "shared", "public_link": "https://..."}, "source_path": "/", "target_path": "data", "readonly": true}

        Do NOT include credentials in the storage configuration. After creating the connector,
        direct the user to add any required secrets (passwords, access keys) through the Renku UI.

        Always pass project_id to link the connector immediately — a connector without a project
        link is orphaned and not visible in any project."""
        is_doi = (storage.get("configuration") or {}).get("type") == "doi"
        if is_doi:
            data = await _api(ctx, "POST", "/data_connectors/global", {"storage": storage})
            if tp := (data.get("storage") or {}).get("target_path"):
                data["_mount_path"] = f"/home/renku/work/{tp}"
        else:
            if not name or not namespace:
                raise RuntimeError("name and namespace are required for non-DOI connectors")
            body: dict[str, Any] = {
                "name": name, "namespace": namespace, "visibility": visibility, "storage": storage,
            }
            data = await _api(ctx, "POST", "/data_connectors", body)
        if project_id:
            data["_link"] = await _api(
                ctx, "POST", f"/data_connectors/{data['id']}/project_links", {"project_id": project_id}
            )
        return data

    @mcp.tool()
    async def connector_link(
        ctx: Context,
        connector_id: Annotated[str, Field(description="Connector ID")],
        project_id: Annotated[str, Field(description="Project ID")],
    ) -> dict[str, Any]:
        """Link an existing data connector to a project."""
        return await _deps(ctx).api(
            "POST", f"/data_connectors/{connector_id}/project_links", _token(ctx), {"project_id": project_id}
        )

    @mcp.tool()
    async def connector_patch(
        ctx: Context,
        connector_id: Annotated[str, Field(description="Connector ID")],
        body: Annotated[dict[str, Any], Field(description="Partial update body")],
    ) -> dict[str, Any]:
        """Patch a data connector (name, namespace, visibility, storage fields, etc.).

        To remove a project-owned connector from a project without deleting it:
          1. Call connector_patch(connector_id, {"namespace": "<your-username>"}) to move it to
             a user namespace — it is now independently owned.
          2. Call connector_unlink(connector_id, link_id) to remove the project association."""
        return await _api(ctx, "PATCH", f"/data_connectors/{connector_id}", body)

    @mcp.tool()
    async def connector_unlink(
        ctx: Context,
        connector_id: Annotated[str, Field(description="Connector ID")],
        link_id: Annotated[str, Field(description="Link ID (from connector_get)")],
    ) -> str:
        """Unlink a data connector from a project.
        Only works when the connector lives in a user or group namespace (not the project itself).
        For connectors that live in a project namespace:
          - To remove it entirely: use connector_delete (no move needed).
          - To detach from the project but keep the connector: use connector_patch to move it to
            a user namespace first, then call connector_unlink."""
        await _api(ctx, "DELETE", f"/data_connectors/{connector_id}/project_links/{link_id}")
        return f"Unlinked connector {connector_id} (link {link_id})"

    @mcp.tool()
    async def connector_delete(
        ctx: Context,
        connector_id: Annotated[str, Field(description="Connector ID")],
    ) -> str:
        """Delete a data connector entirely. Works whether the connector lives in a project
        namespace or a user/group namespace. Confirm with the user before calling.
        To keep the connector but remove it from a project, use connector_unlink (user/group
        namespace) or connector_patch + connector_unlink (project namespace)."""
        await _api(ctx, "DELETE", f"/data_connectors/{connector_id}")
        return f"Deleted connector {connector_id}"

    # ------------------------------------------------------------------ #
    # Session launchers                                                    #
    # ------------------------------------------------------------------ #

    @mcp.tool()
    async def launcher_list(ctx: Context) -> list[dict[str, Any]]:
        """List all session launchers accessible to the user."""
        return await _api(ctx, "GET", "/session_launchers")

    @mcp.tool()
    async def launcher_project_list(
        ctx: Context,
        project_id: Annotated[str, Field(description="Project ID")],
    ) -> list[dict[str, Any]]:
        """List session launchers for a specific project."""
        return await _api(ctx, "GET", f"/projects/{project_id}/session_launchers")

    @mcp.tool()
    async def launcher_get(
        ctx: Context,
        launcher_id: Annotated[str, Field(description="Launcher ID")],
    ) -> dict[str, Any]:
        """Get a session launcher by ID."""
        return await _api(ctx, "GET", f"/session_launchers/{launcher_id}")

    @mcp.tool()
    async def launcher_create(
        ctx: Context,
        project_id: Annotated[str, Field(description="Project ID")],
        name: Annotated[str, Field(description="Launcher name")],
        resource_class_id: Annotated[int, Field(description="Resource class ID (from resource_classes())")],
        environment: Annotated[dict[str, Any], Field(description="Environment definition dict")],
        description: Annotated[str, Field(description="Optional description")] = "",
    ) -> dict[str, Any]:
        """Create a session launcher. Always call resource_classes(cpu=..., memory=...) first.

        Three ways to specify the environment:

        1. Global environment (user has no image or repo): pass {"id": "<environment_id>"}
           using an id from global_environments(). No other fields needed.

        2. Build from code ('build'): include environment_image_source='build', repository,
           builder_variant, frontend_variant. Do NOT include 'name'.
           After creating, call build_list(environment_id) → build_wait(build_id) before
           launching — the image must finish building first. Do not sleep or poll manually.

        3. Custom image ('image'): include environment_image_source='image',
           environment_kind='CUSTOM', container_image,
           working_directory='/home/renku/work', mount_directory='/home/renku/work',
           command=['/cnb/lifecycle/launcher'], args, port, uid, gid."""
        # 'name' is required for image-source environments but rejected by BuildParametersPost.
        if environment.get("environment_image_source") != "build" and "name" not in environment:
            environment = {"name": name, **environment}
        body: dict[str, Any] = {
            "project_id": project_id, "name": name,
            "resource_class_id": resource_class_id, "environment": environment,
        }
        if description:
            body["description"] = description
        return _launcher_summary(await _api(ctx, "POST", "/session_launchers", body))

    @mcp.tool()
    async def launcher_patch(
        ctx: Context,
        launcher_id: Annotated[str, Field(description="Launcher ID")],
        resource_class_id: Annotated[int | None, Field(description="New resource class ID")] = None,
        name: Annotated[str | None, Field(description="New launcher name")] = None,
        environment: Annotated[dict[str, Any] | None, Field(description="Partial or full environment dict")] = None,
    ) -> dict[str, Any]:
        """Patch a session launcher. Omit any field to leave it unchanged."""
        body: dict[str, Any] = {}
        if resource_class_id is not None:
            body["resource_class_id"] = resource_class_id
        if name is not None:
            body["name"] = name
        if environment is not None:
            body["environment"] = environment
        if not body:
            raise RuntimeError("launcher_patch: provide at least one field to update")
        return _launcher_summary(await _api(ctx, "PATCH", f"/session_launchers/{launcher_id}", body))

    @mcp.tool()
    async def launcher_delete(
        ctx: Context,
        launcher_id: Annotated[str, Field(description="Launcher ID")],
    ) -> str:
        """Delete a session launcher. Confirm with the user before calling."""
        await _api(ctx, "DELETE", f"/session_launchers/{launcher_id}")
        return f"Deleted launcher {launcher_id}"

    # ------------------------------------------------------------------ #
    # Groups                                                               #
    # ------------------------------------------------------------------ #

    @mcp.tool()
    async def renku_group_members(
        ctx: Context,
        group_slug: Annotated[str, Field(description="Group slug")],
    ) -> list[dict[str, Any]]:
        """List members of a Renku group."""
        return await _api(ctx, "GET", f"/groups/{group_slug}/members")

    # ------------------------------------------------------------------ #
    # Data connector link helpers                                          #
    # ------------------------------------------------------------------ #

    @mcp.tool()
    async def renku_connector_project_links(
        ctx: Context,
        connector_id: Annotated[str, Field(description="Data connector ID")],
    ) -> list[dict[str, Any]]:
        """List all project links for a data connector (which projects use it)."""
        return await _api(ctx, "GET", f"/data_connectors/{connector_id}/project_links")

    @mcp.tool()
    async def renku_project_data_connector_links(
        ctx: Context,
        project_id: Annotated[str, Field(description="Project ID")],
    ) -> list[dict[str, Any]]:
        """List all data connector links for a project (which connectors it uses)."""
        return await _api(ctx, "GET", f"/projects/{project_id}/data_connector_links")

    # ------------------------------------------------------------------ #
    # Sessions                                                             #
    # ------------------------------------------------------------------ #

    @mcp.tool()
    async def session_launch(
        ctx: Context,
        launcher_id: Annotated[str, Field(description="Launcher ID")],
        resource_class_id: Annotated[int | None, Field(description="Override resource class")] = None,
        disk_storage: Annotated[int | None, Field(description="Override disk storage in GB")] = None,
    ) -> dict[str, Any]:
        """Launch an interactive session from a launcher.
        After calling this, use session_wait(session_id) to wait for it to reach
        'running' state — do not sleep or poll manually."""
        body: dict[str, Any] = {"launcher_id": launcher_id, "session_type": "interactive"}
        if resource_class_id is not None:
            body["resource_class_id"] = resource_class_id
        if disk_storage is not None:
            body["disk_storage"] = disk_storage
        return await _api(ctx, "POST", "/sessions", body)

    @mcp.tool()
    async def session_list(
        ctx: Context,
        session_type: Annotated[str, Field(description="'interactive' or 'non-interactive'")] = "interactive",
        project_id: Annotated[str, Field(description="Optional project ID filter")] = "",
    ) -> list[dict[str, Any]]:
        """List sessions, filtering out stale hibernated records."""
        query: dict[str, Any] = {"session_type": session_type}
        if project_id:
            query["project_id"] = project_id
        sessions = await _api(ctx, "GET", "/sessions", query=query)
        if not isinstance(sessions, list):
            return sessions
        return [s for s in sessions if not _is_stale_session(s)]

    @mcp.tool()
    async def session_get(
        ctx: Context,
        session_id: Annotated[str, Field(description="Session name or ID")],
    ) -> dict[str, Any]:
        """Get session status and details."""
        return await _api(ctx, "GET", f"/sessions/{session_id}")

    @mcp.tool()
    async def session_logs(
        ctx: Context,
        session_id: Annotated[str, Field(description="Session name or ID")],
    ) -> dict[str, Any]:
        """Get logs for a session.
        Returns a dict of container_name -> log_text.
        The 'amalthea-session' container holds the main application logs."""
        return await _api(ctx, "GET", f"/sessions/{session_id}/logs")

    @mcp.tool()
    async def session_delete(
        ctx: Context,
        session_id: Annotated[str, Field(description="Session name or ID")],
    ) -> str:
        """Stop and delete a session. Confirm with the user before calling."""
        await _api(ctx, "DELETE", f"/sessions/{session_id}")
        return f"Deleted session {session_id}"

    @mcp.tool()
    async def session_delete_if_failed(
        ctx: Context,
        session_id: Annotated[str, Field(description="Session name or ID")],
    ) -> str:
        """Delete a session if it is in any terminal state (failed, error, stopped, succeeded,
        completed, finished). Safe no-op if the session is still running or starting.
        Use this before job_run to ensure the slot is clear."""
        session = await _api(ctx, "GET", f"/sessions/{session_id}")
        status = session.get("status") or {}
        state = status.get("state") or session.get("state") or "unknown"
        terminal = {"failed", "error", "stopped", "succeeded", "completed", "finished"}
        if state not in terminal:
            return f"Session {session_id} is in state '{state}' — not deleted."
        await _api(ctx, "DELETE", f"/sessions/{session_id}")
        return f"Deleted session {session_id} (was {state})"

    @mcp.tool()
    async def session_wait(
        ctx: Context,
        session_id: Annotated[str, Field(description="Session name or ID")],
        timeout: Annotated[int, Field(description="Maximum wait time in seconds", ge=1)] = 900,
        interval: Annotated[int, Field(description="Poll interval in seconds", ge=1)] = 10,
    ) -> dict[str, Any]:
        """Wait for an interactive session to reach 'running' state.
        Returns the final state dict; includes logs on failure.
        On timeout returns {"state": <last_state>, "timed_out": true} — always check
        timed_out before assuming the session is running."""
        import asyncio

        terminal = {"running", "succeeded", "failed", "error", "stopped"}
        success = {"running", "succeeded"}
        deadline = time.time() + timeout
        session: dict[str, Any] = {}
        state = "unknown"
        poll = 3.0
        while time.time() < deadline:
            session = await _api(ctx, "GET", f"/sessions/{session_id}")
            status = session.get("status") or {}
            state = status.get("state") or session.get("state") or "unknown"
            if state in terminal:
                result: dict[str, Any] = {"state": state, "timed_out": False, "session": session}
                if state not in success:
                    try:
                        result["logs"] = await _api(ctx, "GET", f"/sessions/{session_id}/logs")
                    except Exception:
                        pass
                return result
            await asyncio.sleep(min(poll, interval))
            poll = min(poll * 1.5, interval)
        return {"state": state, "timed_out": True, "session": session}

    # ------------------------------------------------------------------ #
    # Jobs                                                                 #
    # ------------------------------------------------------------------ #

    @mcp.tool()
    async def job_run(
        ctx: Context,
        launcher_id: Annotated[str, Field(description="Launcher ID")],
        resource_class_id: Annotated[int | None, Field(description="Override resource class")] = None,
        disk_storage: Annotated[int | None, Field(description="Override disk storage in GB")] = None,
    ) -> dict[str, Any]:
        """Launch a non-interactive job from a launcher.
        Always call resource_classes() first.
        After calling this, use job_wait(session_id) to wait for completion — do not sleep
        or poll manually.

        Pre-flight: call job_list(project_id=...) and check for any existing session from
        the same launcher_id. If one exists in a non-terminal state, call session_delete on
        it first. The platform may silently return an existing session rather than creating
        a new one — always verify _created=true in the response. If _created=false, delete
        the returned session and retry."""
        body: dict[str, Any] = {"launcher_id": launcher_id, "session_type": "non-interactive"}
        if resource_class_id is not None:
            body["resource_class_id"] = resource_class_id
        if disk_storage is not None:
            body["disk_storage"] = disk_storage
        data = await _api(ctx, "POST", "/sessions", body)
        # Detect whether the platform returned a pre-existing session by checking if
        # started_at is more than 60 seconds in the past.
        created = True
        try:
            started_at = data.get("started_at") or (data.get("status") or {}).get("started_at")
            if started_at:
                age = time.time() - datetime.datetime.fromisoformat(
                    started_at.replace("Z", "+00:00")
                ).timestamp()
                created = age < 60
        except Exception:
            pass
        data["_created"] = created
        return data

    @mcp.tool()
    async def job_list(
        ctx: Context,
        project_id: Annotated[str, Field(description="Optional project ID filter")] = "",
    ) -> list[dict[str, Any]]:
        """List non-interactive job sessions, filtering out stale records."""
        query: dict[str, Any] = {"session_type": "non-interactive"}
        if project_id:
            query["project_id"] = project_id
        sessions = await _api(ctx, "GET", "/sessions", query=query)
        if not isinstance(sessions, list):
            return sessions
        return [s for s in sessions if not _is_stale_session(s)]

    @mcp.tool()
    async def job_wait(
        ctx: Context,
        session_id: Annotated[str, Field(description="Session name or ID")],
        timeout: Annotated[int, Field(description="Maximum wait time in seconds", ge=1)] = 1800,
        interval: Annotated[int, Field(description="Poll interval in seconds", ge=1)] = 15,
    ) -> dict[str, Any]:
        """Wait for a non-interactive job to reach a terminal state.
        Polls both session status and logs on every interval so the caller always has
        the latest output. Logs are included in the result regardless of success or failure,
        with amalthea-session first.
        On timeout returns {"state": <last_state>, "timed_out": true} — always check
        timed_out and follow up with job_list to confirm actual state before retrying."""
        import asyncio

        terminal = {"succeeded", "completed", "finished", "failed", "error", "stopped"}
        deadline = time.time() + timeout
        session: dict[str, Any] = {}
        state = "unknown"
        logs: Any = None
        poll = 3.0
        while time.time() < deadline:
            session, logs = await asyncio.gather(
                _api(ctx, "GET", f"/sessions/{session_id}"),
                _api(ctx, "GET", f"/sessions/{session_id}/logs"),
                return_exceptions=True,
            )
            if isinstance(session, BaseException):
                session = {}
            if isinstance(logs, BaseException):
                logs = None
            status = session.get("status") or {}
            state = status.get("state") or session.get("state") or "unknown"
            if state in terminal:
                result: dict[str, Any] = {"state": state, "timed_out": False, "session": session}
                if isinstance(logs, dict):
                    result["logs"] = dict(
                        sorted(logs.items(), key=lambda kv: (kv[0] != "amalthea-session", kv[0]))
                    )
                elif logs is not None:
                    result["logs"] = logs
                return result
            await asyncio.sleep(min(poll, interval))
            poll = min(poll * 1.5, interval)
        return {"state": state, "timed_out": True, "session": session, "logs": logs}

    # ------------------------------------------------------------------ #
    # Builds                                                               #
    # ------------------------------------------------------------------ #

    @mcp.tool()
    async def build_list(
        ctx: Context,
        environment_id: Annotated[str, Field(description="Environment ID")],
    ) -> list[dict[str, Any]]:
        """List builds for an environment."""
        return await _api(ctx, "GET", f"/environments/{environment_id}/builds")

    @mcp.tool()
    async def build_get(
        ctx: Context,
        build_id: Annotated[str, Field(description="Build ID")],
    ) -> dict[str, Any]:
        """Get build status."""
        return await _api(ctx, "GET", f"/builds/{build_id}")

    @mcp.tool()
    async def build_logs(
        ctx: Context,
        build_id: Annotated[str, Field(description="Build ID")],
    ) -> Any:
        """Get build logs."""
        return await _api(ctx, "GET", f"/builds/{build_id}/logs")

    @mcp.tool()
    async def build_wait(
        ctx: Context,
        build_id: Annotated[str, Field(description="Build ID")],
        timeout: Annotated[int, Field(description="Maximum wait time in seconds", ge=1)] = 1800,
        interval: Annotated[int, Field(description="Poll interval in seconds", ge=1)] = 15,
    ) -> dict[str, Any]:
        """Wait for an image build to complete. Returns final state; includes logs on failure."""
        import asyncio

        terminal = {"succeeded", "failed", "error"}
        deadline = time.time() + timeout
        build: dict[str, Any] = {}
        state = "unknown"
        poll = 3.0
        while time.time() < deadline:
            build = await _api(ctx, "GET", f"/builds/{build_id}")
            state = build.get("status", "unknown")
            if state in terminal:
                result: dict[str, Any] = {"state": state, "timed_out": False, "build": build}
                if state != "succeeded":
                    try:
                        result["logs"] = await _api(ctx, "GET", f"/builds/{build_id}/logs")
                    except Exception:
                        pass
                return result
            await asyncio.sleep(min(poll, interval))
            poll = min(poll * 1.5, interval)
        return {"state": state, "timed_out": True, "build": build}

    return mcp
