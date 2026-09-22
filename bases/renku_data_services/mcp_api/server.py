"""FastMCP server — all tools call the Renku REST API."""

from __future__ import annotations

import asyncio
import contextvars
import os
import time
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, suppress
from typing import Annotated, Any
from urllib.parse import quote, urlparse

from mcp import types as mcp_types
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.server import Context
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel, Field

from renku_data_services.mcp_api.client import RenkuApiClient

# Current request token — set by ASGI auth middleware (HTTP) or resolved lazily in stdio mode.
_current_token: contextvars.ContextVar[str] = contextvars.ContextVar("mcp_token", default="")


def set_current_token(token: str) -> contextvars.Token[str]:
    """Store the Bearer token in the current async context."""
    return _current_token.set(token)


def _token(ctx: Context) -> str:
    t = _current_token.get()
    if t:
        return t
    # In stdio mode, ask the resolver for the token from the environment.
    resolver: Callable[[], str] | None = ctx.request_context.lifespan_context.get("token_resolver")
    if resolver:
        try:
            t = resolver()
            if t:
                set_current_token(t)  # cache for this session once found
                return t
        except Exception as exc:
            from renku_data_services.mcp_api.main import TokenNotFoundError

            if isinstance(exc, TokenNotFoundError):
                # No token available — return empty and let the API return 401.
                pass
            else:
                raise
    return ""


def _client(ctx: Context) -> RenkuApiClient:
    return ctx.request_context.lifespan_context["api"]


# Token whose admin status has already been checked in this context. Scoped to the
# context rather than kept in a module-level dict: a dict keyed by token would hold
# live credentials for the process lifetime, and go stale for exactly as long. The
# token is stored alongside the flag so a context serving a different token always
# re-checks.
_admin_checked_token: contextvars.ContextVar[str] = contextvars.ContextVar("mcp_admin_checked", default="")


async def _require_non_admin(ctx: Context) -> None:
    """Raise if the current user is a Renku admin.

    Admin accounts have platform-wide write access that bypasses normal
    permission checks — running agent operations as an admin is dangerous.
    Set RENKU_MCP_ALLOW_ADMIN=1 in the server environment to override.

    Checked once per tool call, not once per API call: the wait tools poll up to
    ~120 times, and re-checking on every poll would double their request volume.
    """

    if os.environ.get("RENKU_MCP_ALLOW_ADMIN") == "1":
        return
    t = _token(ctx)
    if not t:
        return
    if _admin_checked_token.get() == t:
        return
    # Direct client call, not _api(): going through _api() would recurse.
    user = await _client(ctx).request("GET", "/user", t)
    if user.get("is_admin", False):
        raise RuntimeError(
            "Refusing to operate as a Renku admin. "
            "Log out and log back in as a non-admin account, "
            "or set RENKU_MCP_ALLOW_ADMIN=1 to override."
        )
    _admin_checked_token.set(t)


async def _api(ctx: Context, method: str, path: str, body: Any = None, **kwargs: Any) -> Any:
    """Make an authenticated API call, refusing if the current user is an admin."""
    await _require_non_admin(ctx)
    return await _client(ctx).request(method, path, _token(ctx), body, **kwargs)


async def _poll_get(ctx: Context, path: str) -> dict[str, Any]:
    """GET during a wait loop, always returning a dict so callers can read fields off it.

    Failures propagate: a deleted session or an unreachable API ends the wait with an error
    the agent can act on, rather than being absorbed until the timeout expires.
    """
    value = await _api(ctx, "GET", path)
    return value if isinstance(value, dict) else {}


# ---------------------------------------------------------------------------
# Guardrails enforced in code rather than asked for in the instructions
# ---------------------------------------------------------------------------

# Every option rclone marks as sensitive, across all providers. The data API replaces such
# values with a "<sensitive>" placeholder rather than storing them, so a credential sent here
# never persists — but it has already passed through the agent's context and every log between
# here and the API, which is what refusing it prevents.
#
# Copied from the schema rather than imported: reading it at runtime would pull the storage,
# app_config and errors components plus a bundled schema file into a service that otherwise has
# six dependencies. test_secret_field_list_matches_rclone_schema fails if the schema grows a
# sensitive option missing from this list, so the copy cannot drift silently. Regenerate with:
#
#     poetry run python -c "from renku_data_services.storage.rclone import RCloneValidator; \
#     print(sorted({o.name for p in RCloneValidator().providers.values() \
#     for o in p.options if getattr(o, 'sensitive', False)}))"
_RCLONE_SECRET_OPTIONS = frozenset(
    {
        "access_key_id",
        "bearer_token",
        "client_access_token",
        "client_id",
        "client_refresh_token",
        "client_salted_key_pass",
        "client_secret",
        "client_uid",
        "drive_id",
        "impersonate",
        "key",
        "key_pem",
        "link_password",
        "msi_client_id",
        "msi_mi_res_id",
        "msi_object_id",
        "pass",
        "resource_key",
        "root_folder_id",
        "sas_url",
        "secret_access_key",
        "service_account_credentials",
        "session_token",
        "sse_customer_key",
        "sse_customer_key_base64",
        "sse_customer_key_md5",
        "sse_kms_key_id",
        "team_drive",
        "tenant",
        "token",
        "user",
        "username",
    }
)

# Catches secret-looking keys that are not rclone options at all — a field invented by an
# agent, or one added to some future backend. Endpoints and file paths are not secrets.
_SECRET_KEY_PARTS = ("password", "passwd", "secret", "credential", "passphrase", "api_key", "private_key")
_SECRET_KEY_ALLOWED_SUFFIXES = ("_file", "_path", "_url")


def _is_secret_key(key: str) -> bool:
    """Whether a configuration key is one that carries a credential."""
    name = key.strip().lower()
    if name in _RCLONE_SECRET_OPTIONS:
        return True
    if name.endswith(_SECRET_KEY_ALLOWED_SUFFIXES):
        return False
    return any(part in name for part in _SECRET_KEY_PARTS)


def _secret_keys(value: Any, path: str = "") -> list[str]:
    """Return the dotted paths of every key that looks like it carries a secret."""
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            here = f"{path}.{key}" if path else str(key)
            # An empty value carries no secret — it is a field the user will fill in later.
            if _is_secret_key(str(key)) and child not in (None, ""):
                found.append(here)
            found.extend(_secret_keys(child, here))
    elif isinstance(value, list):
        for i, child in enumerate(value):
            found.extend(_secret_keys(child, f"{path}[{i}]"))
    return found


def _reject_secrets(value: Any, what: str) -> None:
    """Refuse a payload that carries credentials, naming the offending fields."""
    keys = _secret_keys(value)
    if not keys:
        return
    raise RuntimeError(
        f"Refusing to send credentials to the API: {what} contains {', '.join(sorted(keys))}. "
        "Credentials must never be passed as tool arguments — they end up in the conversation "
        "and in logs. Create the connector without them, then tell the user to add the secrets "
        "through the Renku UI."
    )


class _Confirmation(BaseModel):
    """Schema for a yes/no confirmation asked of the user via elicitation."""

    confirm: bool = Field(description="Confirm that this operation should go ahead")


async def _require_confirmation(ctx: Context, action: str, *, confirmed: bool) -> None:
    """Get the user's agreement before doing something destructive.

    Asks the user through the client when the client supports elicitation, which makes this
    a step the agent cannot skip. Clients without that capability get a refusal telling the
    agent to confirm and call again with confirm=true — weaker, since the agent can assert
    it, but at least deliberate and visible in the call.
    """
    if confirmed:
        return
    supports_elicitation = ctx.session.check_client_capability(
        mcp_types.ClientCapabilities(elicitation=mcp_types.ElicitationCapability())
    )
    if not supports_elicitation:
        raise RuntimeError(
            f"{action} needs the user's confirmation, and this client cannot be asked directly. "
            "Ask the user, and only if they agree call this tool again with confirm=true."
        )
    result = await ctx.elicit(message=f"{action}. Go ahead?", schema=_Confirmation)
    if result.action != "accept" or not result.data.confirm:
        raise RuntimeError(f"The user did not agree to this: {action}. Do not retry it.")


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
    if "/" in ident:
        ns, slug = ident.split("/", 1)
        return f"/namespaces/{quote(ns, safe='')}/projects/{quote(slug, safe='')}"
    return f"/projects/{quote(ident, safe='')}"


def create_server(
    api: RenkuApiClient,
    token_resolver: Callable[[], str] | None = None,
) -> FastMCP:
    """Create and return the configured FastMCP server.

    api: client used by every tool to reach the Renku data API.
    token_resolver: optional callable returning the token from the environment (stdio
    mode). When provided, _token() calls it on the first request that needs a token,
    so a missing token surfaces as a tool error rather than a startup crash.
    """

    @asynccontextmanager
    async def lifespan(server: FastMCP) -> AsyncIterator[dict[str, Any]]:
        yield {"api": api, "token_resolver": token_resolver}

    # Allow the deployment hostname so the MCP SDK's DNS-rebinding protection
    # doesn't reject requests that arrive with the public hostname as Host header.
    _base_host = urlparse(api.base_url).hostname or ""
    _transport_security = (
        TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=["127.0.0.1:*", "localhost:*", _base_host, f"{_base_host}:*"],
            allowed_origins=[api.base_url, f"{api.base_url}/*"],
        )
        if _base_host
        else None
    )

    mcp = FastMCP(
        "Renku",
        lifespan=lifespan,
        transport_security=_transport_security,
        instructions=(
            "Tools for the Renku data science platform.\n\n"
            "Authentication:\n"
            "- Call auth_status first. If authenticated=false, stop immediately and tell the user "
            "their Renku token is missing or expired. Do not attempt other tools.\n"
            "- If any tool returns an error containing 'Bearer', '401', 'Unauthorized', or "
            "'authenticated: false', treat it as an auth failure — not an API or schema problem. "
            "Stop retrying other tools and ask the user to re-authenticate.\n"
            "- In stdio mode: tell the user to set RENKU_ACCESS_TOKEN in the MCP server's "
            "environment configuration and restart the server. The token is read from the "
            "environment at startup, so a token added afterwards is not picked up until then.\n"
            "- In HTTP mode (remote server): tell the user to reconnect the MCP server in their "
            "client (Claude Code, pi, Codex) to trigger a new OAuth login.\n\n"
            "Safety rules:\n"
            "- If auth_status shows is_admin=true, do not perform any operation. "
            "Ask the user to log out and log back in as a non-admin.\n"
            "- Always call resource_classes(cpu=..., memory=..., gpu=...) before creating a launcher "
            "or running a job, passing your requirements so matching=true is set correctly. "
            "Pick the smallest class where matching=true and pass its id.\n"
            "- Always pass project_id to connector_create so the connector is linked immediately. "
            "Without it the connector appears in no project, so the tool stops and asks the user.\n"
            "- Never put credentials in connector storage configurations or patch bodies. The tools "
            "refuse them outright — create the connector first, then have the user add secrets "
            "through the Renku UI.\n"
            "- Deleting a project, connector, launcher, session or app asks the user to confirm. "
            "Do not set confirm=true to skip that; it exists only for clients that cannot show a "
            "prompt, and then only after the user has actually agreed.\n"
            "- Never sleep or poll manually while waiting for sessions, jobs, builds, or apps. "
            "Always use session_wait(), job_wait(), build_wait(), or app_wait() instead.\n\n"
            "Apps:\n"
            "An app is a long-running deployment served to anonymous visitors, created from a "
            "launcher with launcher_type='app' and started with app_launch().\n"
            "- The project must be public, and a project can have only one app. Check with "
            "app_list(project_id=...) before launching, and never change a project's visibility "
            "without asking the user first.\n"
            "- The app name is generated by the platform, so read it from the app_launch response "
            "rather than constructing it.\n"
            "- Only public, credential-free data connectors are mounted into an app. If the user "
            "expects private data there, tell them it will not be mounted.\n"
            "An 'app' launcher gets its image the same two ways any launcher does:\n"
            "1. Bring your own image: environment_image_source='image' with container_image, port, "
            "uid, gid and command/args. The container runs as non-root with all capabilities "
            "dropped, so an image that insists on root will not start.\n"
            "2. Build from code: environment_image_source='build' with repository, builder_variant "
            "and frontend_variant. For an app pass frontend_variant='none' — the session frontends "
            "(jupyterlab, vscodium, ttyd) are for interactive sessions, and 'none' adds no frontend "
            "so the app itself is what gets served. The buildpack then takes the start command from "
            "a Procfile in the repository, which needs a 'web:' process, since with no frontend "
            "nothing else tells it how to serve the app. Call build_list(environment_id) then "
            "build_wait(build_id) and let the image finish before app_launch.\n"
            "Whichever way, the served process MUST bind $RENKU_SESSION_PORT on $RENKU_SESSION_IP "
            "(0.0.0.0). This is the most common way an app fails: bind the buildpack's default port "
            "instead and Knative never probes the right port, so the app stays 'pending' and then "
            "fails with nothing obviously wrong in the logs.\n"
            "Apps are served at the root of their own hostname, so — unlike sessions — there is no "
            "RENKU_BASE_URL_PATH and no path prefix to configure. Do not apply the session base-path "
            "guidance below to an app.\n\n"
            "Session URLs:\n"
            "Always construct session UI URLs as "
            "{base_url}/p/<namespace>/<project-slug>/sessions/show/<session-name>. "
            "Do NOT use the url field from the session API response — it returns an internal path, "
            "not the correct UI URL.\n\n"
            "Web apps inside Renku sessions (sessions only — not apps, see above):\n"
            "Renku proxies all session traffic under a path prefix. "
            "Inside a session container these environment variables are set:\n"
            "- RENKU_BASE_URL_PATH: the URL path prefix (e.g. /sessions/my-session-abc123)\n"
            "- RENKU_BASE_URL: the full base URL including the path prefix\n"
            "- RENKU_SESSION_PORT: the port the app should listen on\n"
            "- RENKU_SESSION_IP: the address to bind to (0.0.0.0)\n"
            "Web frameworks must be configured to serve from RENKU_BASE_URL_PATH, not /. "
            "Examples: Streamlit --server.baseUrlPath $RENKU_BASE_URL_PATH, "
            "Dash requests_pathname_prefix=$RENKU_BASE_URL_PATH/, "
            "FastAPI root_path=$RENKU_BASE_URL_PATH."
        ),
    )

    # ------------------------------------------------------------------ #
    # Auth / platform                                                      #
    # ------------------------------------------------------------------ #

    @mcp.tool()
    async def auth_status(ctx: Context) -> dict[str, Any]:
        """Return current authentication status and user info.

        Always call this first; refuse all operations if is_admin is true.
        """
        t = _token(ctx)
        base_url = _client(ctx).base_url
        if not t:
            return {
                "authenticated": False,
                "base_url": base_url,
                "hint": "Set RENKU_ACCESS_TOKEN in the MCP server's environment and restart it.",
            }
        try:
            # Direct client call, not _api(): this tool must work for admins too,
            # since reporting is_admin=true is the whole point of calling it.
            user = await _client(ctx).request("GET", "/user", t)
            return {
                "authenticated": True,
                "base_url": base_url,
                "user": user,
                "is_admin": user.get("is_admin", False),
            }
        except RuntimeError as exc:
            return {"authenticated": False, "base_url": base_url, "error": str(exc)}

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
        suitable classes. Pick the smallest class where matching=true.
        """
        query = {
            k: v
            for k, v in {"cpu": cpu, "memory": memory, "gpu": gpu, "max_storage": max_storage}.items()
            if v is not None
        }
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
        environment when calling launcher_create.
        """
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
        return await _api(ctx, "GET", _project_path(project))

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
        they want to add, add it here instead of with project_repo_add to do it all in one call.
        """
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
        confirm: Annotated[bool, Field(description="Set only after the user has agreed to the deletion")] = False,
    ) -> str:
        """Delete a Renku project. Irreversible — the user is asked to confirm before it proceeds.

        Before deleting, call session_list(project_id=<id>) for both session types and
        job_list(project_id=<id>). Then:
        - Inform the user about the running sessions and pending jobs that will be stopped.
        - Running or pending sessions: stop them with session_delete.
        - Hibernated or paused sessions: warn the user that unsaved work inside those
          sessions will be lost.
        """
        proj = await _api(ctx, "GET", _project_path(project))
        await _require_confirmation(
            ctx,
            f"Permanently delete project {proj.get('name') or proj['id']!r} and everything in it",
            confirmed=confirm,
        )
        await _api(ctx, "DELETE", f"/projects/{proj['id']}")
        return f"Deleted project {proj['id']} ({proj.get('name', '')})"

    @mcp.tool()
    async def project_repo_add(
        ctx: Context,
        project: Annotated[str, Field(description="Project ID or namespace/slug")],
        repository_url: Annotated[str, Field(description="Git URL to add")],
    ) -> dict[str, Any]:
        """Add a Git repository URL to a project's repositories list."""
        resp = await _api(ctx, "GET", _project_path(project), full_response=True)
        proj = resp.body
        etag = resp.headers.get("ETag") or resp.headers.get("etag") or proj.get("etag")
        if not etag:
            raise RuntimeError("Could not get project ETag — cannot PATCH safely")
        repos = list(proj.get("repositories") or [])
        if repository_url not in repos:
            repos.append(repository_url)
        return await _api(
            ctx,
            "PATCH",
            f"/projects/{proj['id']}",
            {"repositories": repos},
            extra_headers={"If-Match": etag},
        )

    @mcp.tool()
    async def project_update(
        ctx: Context,
        project_id: Annotated[str, Field(description="Project ULID")],
        name: Annotated[str | None, Field(description="New project name")] = None,
        description: Annotated[str | None, Field(description="Short project description (shown in listings)")] = None,
        documentation: Annotated[str | None, Field(description="Long-form project documentation (markdown)")] = None,
        keywords: Annotated[list[str] | None, Field(description="Project keywords (replaces existing list)")] = None,
        visibility: Annotated[str | None, Field(description="'public' or 'private'")] = None,
    ) -> dict[str, Any]:
        """Update project metadata. Omit any field to leave it unchanged.

        Use description for a short summary shown in listings.
        Use documentation for longer markdown content — project README, usage instructions, etc.
        keywords replaces the entire keyword list — include all desired keywords, not just new ones.
        """
        proj = await _api(ctx, "GET", f"/projects/{project_id}")
        etag = proj.get("etag")
        if not etag:
            raise RuntimeError("Could not get project ETag — cannot PATCH safely")
        body: dict[str, Any] = {}
        if name is not None:
            body["name"] = name
        if description is not None:
            body["description"] = description
        if documentation is not None:
            body["documentation"] = documentation
        if keywords is not None:
            body["keywords"] = keywords
        if visibility is not None:
            body["visibility"] = visibility
        if not body:
            raise RuntimeError("project_update: provide at least one field to update")
        return await _api(ctx, "PATCH", f"/projects/{project_id}", body, extra_headers={"If-Match": etag})

    @mcp.tool()
    async def project_get_documentation(
        ctx: Context,
        project_id: Annotated[str, Field(description="Project ULID")],
    ) -> dict[str, Any]:
        """Get a project including its full documentation field (not returned by project_get by default)."""
        return await _api(ctx, "GET", f"/projects/{project_id}", query={"with_documentation": "true"})

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
        name: Annotated[
            str | None, Field(description="Connector display name (required for namespaced connectors)")
        ] = None,
        namespace: Annotated[
            str | None, Field(description="Namespace slug (required for namespaced connectors)")
        ] = None,
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

        Credentials in the storage configuration are refused, not ignored — create the connector
        without them and direct the user to add secrets through the Renku UI.

        Always pass project_id to link the connector immediately. Creating one without a project
        link leaves it visible only in its namespace, so the tool asks the user to confirm first.
        """
        _reject_secrets(storage, "the storage configuration")
        if not project_id:
            await _require_confirmation(
                ctx,
                f"Create data connector {name or 'from DOI'!r} without linking it to a project, "
                "so it will not appear in any project",
                confirmed=False,
            )
        is_doi = (storage.get("configuration") or {}).get("type") == "doi"
        if is_doi:
            data = await _api(ctx, "POST", "/data_connectors/global", {"storage": storage})
            if tp := (data.get("storage") or {}).get("target_path"):
                data["_mount_path"] = f"/home/renku/work/{tp}"
        else:
            if not name or not namespace:
                raise RuntimeError("name and namespace are required for non-DOI connectors")
            body: dict[str, Any] = {
                "name": name,
                "namespace": namespace,
                "visibility": visibility,
                "storage": storage,
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
        return await _api(ctx, "POST", f"/data_connectors/{connector_id}/project_links", {"project_id": project_id})

    @mcp.tool()
    async def connector_patch(
        ctx: Context,
        connector_id: Annotated[str, Field(description="Connector ID")],
        body: Annotated[dict[str, Any], Field(description="Partial update body")],
    ) -> dict[str, Any]:
        """Patch a data connector.

        Patchable fields: name, namespace, visibility, storage,
        description, keywords (list of strings, replaces existing list).

        To remove a project-owned connector from a project without deleting it:
          1. Call connector_patch(connector_id, {"namespace": "<your-username>"}) to move it to
             a user namespace — it is now independently owned.
          2. Call connector_unlink(connector_id, link_id) to remove the project association.

        Credentials in the patch body are refused; secrets belong in the Renku UI.
        """
        _reject_secrets(body, "the patch body")
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
            a user namespace first, then call connector_unlink.
        """
        await _api(ctx, "DELETE", f"/data_connectors/{connector_id}/project_links/{link_id}")
        return f"Unlinked connector {connector_id} (link {link_id})"

    @mcp.tool()
    async def connector_delete(
        ctx: Context,
        connector_id: Annotated[str, Field(description="Connector ID")],
        confirm: Annotated[bool, Field(description="Set only after the user has agreed to the deletion")] = False,
    ) -> str:
        """Delete a data connector entirely.

        Works whether the connector lives in a project namespace or a user/group namespace.
        The user is asked to confirm before it proceeds.
        To keep the connector but remove it from a project, use connector_unlink (user/group
        namespace) or connector_patch + connector_unlink (project namespace).
        """
        await _require_confirmation(ctx, f"Delete data connector {connector_id}", confirmed=confirm)
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
        launcher_type: Annotated[
            str | None,
            Field(
                description="'non-interactive' for job launchers, 'app' for apps. "
                "Leave unset for interactive sessions (the default)."
            ),
        ] = None,
        description: Annotated[str, Field(description="Optional description")] = "",
    ) -> dict[str, Any]:
        """Create a session launcher. Always call resource_classes(cpu=..., memory=...) first.

        launcher_type selects what the launcher produces: omit it for an interactive session,
        'non-interactive' for a job to run with job_run, or 'app' for a publicly served
        deployment to start with app_launch. An 'app' launcher is only accepted in a public
        project — in a private one, creation fails, so ask the user before making a project
        public. Underscores are normalised to hyphens, but the API's own values are hyphenated.
        Leave launcher_type unset rather than sending 'interactive': older deployments reject it.

        Choosing the right environment strategy:
        If the project has a Git repository attached (check the 'repositories' field from
        project_get), inspect the repo for these files before choosing an environment type:
          requirements.txt         → Python/pip
          pyproject.toml + uv.lock → Python/uv
          pyproject.toml + poetry.lock → Python/Poetry
          environment.yml          → Python/conda
          renv.lock                → R/renv
          *.R files + no renv.lock → R (basic)
        If any of these are present, ask the user whether to build a custom image from the
        repo (option 2 below) rather than using a global environment. Building from the repo
        installs the project's exact dependencies and is usually the right choice.

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
           command=['/cnb/lifecycle/launcher'], args, port, uid, gid.

        For launcher_type='app', options 2 and 3 are both fine, but the served process must
        bind $RENKU_SESSION_PORT on 0.0.0.0 — an app that listens anywhere else never becomes
        ready. With option 2 pass frontend_variant='none' (jupyterlab/vscodium/ttyd are session
        frontends) and give the repo a Procfile with a 'web:' process that honours
        $RENKU_SESSION_PORT — with no frontend, that process is the app. With option 3 the image
        must run as non-root, since apps drop all capabilities. Apps get no RENKU_BASE_URL_PATH —
        they are served at the root of their own hostname, so skip the base-path configuration
        described below.

        Session environment variables — available inside every running session/job container:
          RENKU_BASE_URL_PATH  URL path prefix for the session (e.g. /sessions/my-session-abc)
          RENKU_BASE_URL       Full base URL including the path prefix
          RENKU_SESSION_PORT   Port the app must listen on
          RENKU_SESSION_IP     Address to bind to (0.0.0.0)
          RENKU_SESSION        Set to "1" to detect Renku environment

        Web apps must handle the path prefix. Two approaches:

        Preferred — configure the app to use RENKU_BASE_URL_PATH as its base path:
          Streamlit:  streamlit run app.py --server.baseUrlPath $RENKU_BASE_URL_PATH
          Dash:       app = Dash(__name__, requests_pathname_prefix=os.environ['RENKU_BASE_URL_PATH'] + '/')
          FastAPI:    app = FastAPI(root_path=os.environ['RENKU_BASE_URL_PATH'])
          Panel:      pn.serve(..., prefix=os.environ['RENKU_BASE_URL_PATH'])

        Alternative — if the framework cannot be configured to use a base path, enable
        strip_path_prefix on the launcher's environment so Renku strips the prefix before
        forwarding. Use launcher_patch with {"environment": {"strip_path_prefix": true}}.
        The app then receives requests at / as normal, but loses the ability to generate
        correct absolute URLs.
        """
        # 'name' is required for image-source environments but rejected by BuildParametersPost.
        if environment.get("environment_image_source") != "build" and "name" not in environment:
            environment = {"name": name, **environment}
        body: dict[str, Any] = {
            "project_id": project_id,
            "name": name,
            "resource_class_id": resource_class_id,
            "environment": environment,
        }
        if launcher_type is not None:
            # The API enum is hyphenated ('non-interactive'); accept the underscored
            # spelling agents tend to produce rather than failing validation.
            body["launcher_type"] = launcher_type.replace("_", "-")
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
        confirm: Annotated[bool, Field(description="Set only after the user has agreed to the deletion")] = False,
    ) -> str:
        """Delete a session launcher. The user is asked to confirm before it proceeds."""
        await _require_confirmation(ctx, f"Delete session launcher {launcher_id}", confirmed=confirm)
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

        Verifies the launcher has launcher_type='interactive' — use job_run for non_interactive launchers.
        After calling this, use session_wait(session_id) to wait for 'running' state —
        do not sleep or poll manually.
        """
        launcher = await _api(ctx, "GET", f"/session_launchers/{launcher_id}")
        # Normalise hyphen/underscore variants returned by different API versions.
        # None means the API predates launcher_type — treat as interactive (the historical default).
        launcher_type = (launcher.get("launcher_type") or "").replace("-", "_")
        if launcher_type not in ("interactive", ""):
            raise RuntimeError(
                f"Launcher {launcher_id!r} has launcher_type={launcher.get('launcher_type')!r}. "
                "Use job_run for non_interactive launchers."
            )
        body: dict[str, Any] = {"launcher_id": launcher_id}
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
        """List sessions."""
        query: dict[str, Any] = {"session_type": session_type}
        if project_id:
            query["project_id"] = project_id
        return await _api(ctx, "GET", "/sessions", query=query)

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
        The 'amalthea-session' container holds the main application logs.
        """
        return await _api(ctx, "GET", f"/sessions/{session_id}/logs")

    @mcp.tool()
    async def session_delete(
        ctx: Context,
        session_id: Annotated[str, Field(description="Session name or ID")],
        confirm: Annotated[bool, Field(description="Set only after the user has agreed to stopping it")] = False,
    ) -> str:
        """Stop and delete a session. The user is asked to confirm before it proceeds.

        Unsaved work inside a running or hibernated session is lost. Use
        session_delete_if_failed instead to clear sessions that already stopped — that one
        needs no confirmation, since a terminal session has nothing left to lose.
        """
        await _require_confirmation(
            ctx, f"Stop and delete session {session_id}, losing any unsaved work in it", confirmed=confirm
        )
        await _api(ctx, "DELETE", f"/sessions/{session_id}")
        return f"Deleted session {session_id}"

    @mcp.tool()
    async def session_delete_if_failed(
        ctx: Context,
        session_id: Annotated[str, Field(description="Session name or ID")],
    ) -> str:
        """Delete a session if it is in any terminal state.

        Terminal states: failed, error, stopped, succeeded, completed, finished.
        Safe no-op if the session is still running or starting.
        Use this before job_run to ensure the slot is clear.
        """
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
        timed_out before assuming the session is running.
        """
        terminal = {"running", "succeeded", "failed", "error", "stopped"}
        success = {"running", "succeeded"}
        deadline = time.time() + timeout
        session: dict[str, Any] = {}
        state = "unknown"
        poll = 3.0
        while time.time() < deadline:
            session = await _poll_get(ctx, f"/sessions/{session_id}")
            status = session.get("status") or {}
            state = status.get("state") or session.get("state") or "unknown"
            if state in terminal:
                result: dict[str, Any] = {"state": state, "timed_out": False, "session": session}
                if state not in success:
                    with suppress(Exception):
                        result["logs"] = await _api(ctx, "GET", f"/sessions/{session_id}/logs")
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
        submission_id: Annotated[
            str | None,
            Field(
                description="Unique ID for this job submission (pattern: ^[a-z][-0-9a-z]{3,19}$). "
                "Auto-generated if omitted. Use the same value to retry a failed job for deduplication.",
            ),
        ] = None,
        resource_class_id: Annotated[int | None, Field(description="Override resource class")] = None,
        disk_storage: Annotated[int | None, Field(description="Override disk storage in GB")] = None,
        job_command_override: Annotated[list[str] | None, Field(description="Override the container command")] = None,
        job_args_override: Annotated[list[str] | None, Field(description="Override the container args")] = None,
    ) -> dict[str, Any]:
        """Launch a non-interactive job from a launcher.

        Verifies the launcher has launcher_type='non_interactive' — use session_launch for interactive launchers.
        Always call resource_classes() first.
        After calling this, use job_wait(session_id) to wait for completion — do not sleep
        or poll manually.

        Launching is idempotent: the platform returns an already-running session instead of
        starting a second one when the user, project, launcher, cluster and submission_id all
        match. The response says which happened in _created — true for a session this call
        started, false for one that was already there. On _created=false, either use that
        session or session_delete it and retry with a different submission_id; do not assume
        your job started.
        """
        launcher = await _api(ctx, "GET", f"/session_launchers/{launcher_id}")
        # Normalise hyphen/underscore variants returned by different API versions.
        # None means the API predates launcher_type — treat as interactive, so block job_run.
        launcher_type = (launcher.get("launcher_type") or "").replace("-", "_")
        if launcher_type != "non_interactive":
            raise RuntimeError(
                f"Launcher {launcher_id!r} has launcher_type={launcher.get('launcher_type') or 'interactive (default)'}. "
                "Use session_launch for interactive launchers."
            )
        # submission_id is required by the API for non-interactive jobs; auto-generate if not provided.
        effective_submission_id = submission_id or f"j{uuid.uuid4().hex[:15]}"
        body: dict[str, Any] = {"launcher_id": launcher_id, "submission_id": effective_submission_id}
        if resource_class_id is not None:
            body["resource_class_id"] = resource_class_id
        if disk_storage is not None:
            body["disk_storage"] = disk_storage
        if job_command_override is not None:
            body["job_command_override"] = job_command_override
        if job_args_override is not None:
            body["job_args_override"] = job_args_override
        # The API is idempotent on (user, project, launcher, cluster, submission_id): if such a
        # session already exists it is returned instead of a new one, and says so with 200
        # rather than 201.
        resp = await _api(ctx, "POST", "/sessions", body, full_response=True)
        data: dict[str, Any] = resp.body
        data["_created"] = resp.status == 201
        return data

    @mcp.tool()
    async def job_list(
        ctx: Context,
        project_id: Annotated[str, Field(description="Optional project ID filter")] = "",
    ) -> list[dict[str, Any]]:
        """List non-interactive job sessions."""
        query: dict[str, Any] = {"session_type": "non-interactive"}
        if project_id:
            query["project_id"] = project_id
        return await _api(ctx, "GET", "/sessions", query=query)

    @mcp.tool()
    async def job_wait(
        ctx: Context,
        session_id: Annotated[str, Field(description="Session name or ID")],
        timeout: Annotated[int, Field(description="Maximum wait time in seconds", ge=1)] = 1800,
        interval: Annotated[int, Field(description="Poll interval in seconds", ge=1)] = 15,
    ) -> dict[str, Any]:
        """Wait for a non-interactive job to reach a terminal state.

        Logs are fetched once the wait ends — on success, failure or timeout — and included
        in the result with amalthea-session first.
        On timeout returns {"state": <last_state>, "timed_out": true} — always check
        timed_out and follow up with job_list to confirm actual state before retrying.
        """
        terminal = {"succeeded", "completed", "finished", "failed", "error", "stopped"}
        deadline = time.time() + timeout
        session: dict[str, Any] = {}
        state = "unknown"
        timed_out = True
        poll = 3.0
        while time.time() < deadline:
            session = await _poll_get(ctx, f"/sessions/{session_id}")
            status = session.get("status") or {}
            state = status.get("state") or session.get("state") or "unknown"
            if state in terminal:
                timed_out = False
                break
            await asyncio.sleep(min(poll, interval))
            poll = min(poll * 1.5, interval)

        # Fetched after the loop rather than on every poll: only the final set is ever
        # returned, and a long wait would otherwise repeat this ~120 times for nothing.
        result: dict[str, Any] = {"state": state, "timed_out": timed_out, "session": session}
        logs: Any = None
        with suppress(Exception):
            logs = await _api(ctx, "GET", f"/sessions/{session_id}/logs")
        if isinstance(logs, dict):
            result["logs"] = dict(sorted(logs.items(), key=lambda kv: (kv[0] != "amalthea-session", kv[0])))
        elif logs is not None:
            result["logs"] = logs
        return result

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
        terminal = {"succeeded", "failed", "error"}
        deadline = time.time() + timeout
        build: dict[str, Any] = {}
        state = "unknown"
        poll = 3.0
        while time.time() < deadline:
            build = await _poll_get(ctx, f"/builds/{build_id}")
            state = build.get("status", "unknown")
            if state in terminal:
                result: dict[str, Any] = {"state": state, "timed_out": False, "build": build}
                if state != "succeeded":
                    with suppress(Exception):
                        result["logs"] = await _api(ctx, "GET", f"/builds/{build_id}/logs")
                return result
            await asyncio.sleep(min(poll, interval))
            poll = min(poll * 1.5, interval)
        return {"state": state, "timed_out": True, "build": build}

    # ------------------------------------------------------------------ #
    # Apps                                                                 #
    # ------------------------------------------------------------------ #

    @mcp.tool()
    async def app_launch(
        ctx: Context,
        launcher_id: Annotated[str, Field(description="ID of a launcher created with launcher_type='app'")],
    ) -> dict[str, Any]:
        """Launch an app — a long-running, publicly reachable deployment of a project.

        Unlike a session, an app serves anonymous visitors, so the platform imposes two
        rules that are worth checking before calling this:

        - The project must be public. Both launcher_create and this call reject an 'app'
          launcher in a private project; tell the user their project has to be public and
          let them decide, rather than changing the visibility for them.
        - One app per project. Launching while the project already has an app fails with a
          conflict — call app_list(project_id=...) first and, if the user wants to replace
          the existing app, confirm with them and app_delete it.

        The app name is generated by the platform from the project slug and launcher ID, so
        it is only known from the response. Follow with app_wait(app_name) — do not sleep or
        poll manually.

        Only data connectors that are public and need no credentials are mounted, since the
        app is served anonymously. A connector requiring secrets is silently left out.
        """
        return await _api(ctx, "POST", "/apps", {"launcher_id": launcher_id})

    @mcp.tool()
    async def app_list(
        ctx: Context,
        project_id: Annotated[str | None, Field(description="Only return apps in this project")] = None,
    ) -> list[dict[str, Any]]:
        """List apps visible to the caller, optionally narrowed to one project."""
        query = {"project_id": project_id} if project_id else None
        return await _api(ctx, "GET", "/apps", query=query)

    @mcp.tool()
    async def app_get(
        ctx: Context,
        app_name: Annotated[str, Field(description="App name (from app_launch or app_list)")],
    ) -> dict[str, Any]:
        """Get an app's status and public URL. Status is one of pending, ready, failed.

        'ready' means servable, not warm: an idle app scales to zero and still reports ready,
        so the first visitor after a quiet spell pays a cold start. Such an app also returns
        no logs — ready with empty logs means idle, not broken.
        """
        return await _api(ctx, "GET", f"/apps/{app_name}")

    @mcp.tool()
    async def app_logs(
        ctx: Context,
        app_name: Annotated[str, Field(description="App name")],
        max_lines: Annotated[int | None, Field(description="Maximum log lines per container", ge=1)] = None,
    ) -> Any:
        """Get an app's logs, keyed by '<pod name>/<container name>'.

        An app can be backed by several pods, so expect more than one key. An app that has
        scaled to zero has no pods and therefore returns no logs — that is not an error.
        """
        query = {"max_lines": max_lines} if max_lines is not None else None
        return await _api(ctx, "GET", f"/apps/{app_name}/logs", query=query)

    @mcp.tool()
    async def app_delete(
        ctx: Context,
        app_name: Annotated[str, Field(description="App name")],
        confirm: Annotated[bool, Field(description="Set only after the user has agreed to the deletion")] = False,
    ) -> str:
        """Delete an app. The user is asked to confirm, since this takes it offline for its visitors."""
        await _require_confirmation(
            ctx, f"Delete app {app_name!r}, taking it offline for anyone currently using it", confirmed=confirm
        )
        await _api(ctx, "DELETE", f"/apps/{app_name}")
        return f"Deleted app {app_name}"

    @mcp.tool()
    async def app_wait(
        ctx: Context,
        app_name: Annotated[str, Field(description="App name")],
        timeout: Annotated[int, Field(description="Maximum wait time in seconds", ge=1)] = 900,
        interval: Annotated[int, Field(description="Poll interval in seconds", ge=1)] = 10,
    ) -> dict[str, Any]:
        """Wait for an app to become ready.

        Returns the final state dict; includes logs on failure. On timeout returns
        {"status": <last_status>, "timed_out": true} — always check timed_out before
        telling the user the app is up.
        """
        terminal = {"ready", "failed"}
        deadline = time.time() + timeout
        app: dict[str, Any] = {}
        status = "unknown"
        poll = 3.0
        while time.time() < deadline:
            app = await _poll_get(ctx, f"/apps/{app_name}")
            status = app.get("status") or "unknown"
            if status in terminal:
                result: dict[str, Any] = {"status": status, "timed_out": False, "app": app}
                if status == "failed":
                    with suppress(Exception):
                        result["logs"] = await _api(ctx, "GET", f"/apps/{app_name}/logs")
                return result
            await asyncio.sleep(min(poll, interval))
            poll = min(poll * 1.5, interval)
        return {"status": status, "timed_out": True, "app": app}

    return mcp
