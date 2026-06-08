r"""Entrypoint for the Renku MCP server.

Usage
-----
stdio (local dev / Claude Desktop):
    RENKU_ACCESS_TOKEN=<token> python -m renku_data_services.mcp_api
    # or: rnk login  (token auto-discovered from rnk's token file)

streamable-http (production):
    MCP_TRANSPORT=streamable-http MCP_HOST=0.0.0.0 MCP_PORT=9000 \\
        python -m renku_data_services.mcp_api

Token resolution order
----------------------
1. RENKU_ACCESS_TOKEN, RENKU_TOKEN, or RENKU_CLI_ACCESS_TOKEN env var.
2. Legacy credential files (~/.config/renku-agent-skill/credentials.json, etc.).
3. Official rnk CLI token file (platform-specific path, validated for issuer + expiry).
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from renku_data_services.mcp_api.dependencies import MCPDependencies
from renku_data_services.mcp_api.server import create_server, set_current_token

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Multi-source credential resolution (mirrors the reference standalone server)
# ---------------------------------------------------------------------------


def _base_url() -> str:
    return os.environ.get("RENKU_BASE_URL", "https://renkulab.io").rstrip("/")


def _creds_candidates() -> list[Path]:
    """Legacy credential file paths to search."""
    candidates: list[Path] = []
    if d := os.environ.get("RENKU_CONFIG_DIR"):
        candidates.append(Path(d) / "credentials.json")
    home = Path.home()
    candidates += [
        home / ".config" / "renku-agent-skill" / "credentials.json",
        home / ".pi" / "renku-config" / "credentials.json",
    ]
    return candidates


def _rnk_token_paths() -> list[Path]:
    """Paths where the official rnk CLI stores its token file (platform-specific)."""
    home = Path.home()
    paths: list[Path] = []
    if sys.platform == "darwin":
        paths.append(home / "Library" / "Application Support" / "io.renku.sdsc.renku-cli" / "token.json")
    xdg = Path(os.environ.get("XDG_DATA_HOME", str(home / ".local" / "share")))
    paths.append(xdg / "io.renku.sdsc.renku-cli" / "token.json")
    if appdata := os.environ.get("APPDATA"):
        paths.append(Path(appdata) / "io.renku.sdsc.renku-cli" / "token.json")
    return paths


def _load_rnk_token() -> str | None:
    """Read an access token from the rnk CLI token file, validating issuer and expiry."""
    expected_issuer = _base_url() + "/auth/realms/Renku"
    for path in _rnk_token_paths():
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text())
            response = data.get("response") or data
            access = response.get("access_token")
            if not access:
                continue
            try:
                payload_part = access.split(".")[1]
                payload_part += "=" * (-len(payload_part) % 4)
                payload: dict[str, Any] = json.loads(base64.urlsafe_b64decode(payload_part.encode()))
                if payload.get("iss") != expected_issuer:
                    continue  # token is for a different deployment
                if payload.get("exp") and time.time() > int(payload["exp"]) - 60:
                    continue  # token is expired or expires in < 60 s
            except Exception:
                pass  # accept token anyway if JWT decode fails
            return access
        except Exception:
            continue
    return None


def _resolve_token() -> str:
    """Return the best available token, or raise with a helpful message."""
    # 1. Environment variables (highest priority)
    for var in ("RENKU_ACCESS_TOKEN", "RENKU_TOKEN", "RENKU_CLI_ACCESS_TOKEN"):
        if t := os.environ.get(var):
            return t

    # 2. Legacy credential files
    checked: list[str] = []
    for f in _creds_candidates():
        checked.append(str(f))
        if f.exists():
            try:
                entry = json.loads(f.read_text()).get(_base_url(), {})
                if t := entry.get("access_token") or entry.get("token"):
                    return t
            except Exception:
                pass

    # 3. Official rnk CLI token file
    if t := _load_rnk_token():
        return t

    rnk_paths = [str(p) for p in _rnk_token_paths()]
    raise RuntimeError(
        f"Not authenticated for {_base_url()}.\n"
        f"Run: rnk login\n"
        f"Credentials searched in: {', '.join(checked)}\n"
        f"rnk token paths searched: {', '.join(rnk_paths)}\n"
        f"Or set RENKU_ACCESS_TOKEN in the MCP server environment config."
    )


# ---------------------------------------------------------------------------
# Transport-specific startup
# ---------------------------------------------------------------------------


def _keycloak_issuer_url() -> str:
    """Return the Keycloak realm issuer URL from KEYCLOAK_ISSUER_URL env var."""
    return os.environ.get("KEYCLOAK_ISSUER_URL", "").rstrip("/")


def _protected_resource_doc(base_url: str, keycloak_realm_url: str) -> dict[str, Any]:
    """Build the RFC 9728 protected resource metadata document."""
    doc: dict[str, Any] = {"resource": f"{base_url}/mcp"}
    if keycloak_realm_url:
        doc["authorization_servers"] = [keycloak_realm_url]
    return doc


async def _authorization_server_doc(keycloak_realm_url: str) -> tuple[dict[str, Any], int]:
    """Fetch and reformat Keycloak OIDC discovery as RFC 8414 AS metadata.

    Returns (body_dict, status_code).
    """
    import httpx

    if not keycloak_realm_url:
        return {"error": "KEYCLOAK_ISSUER_URL not configured"}, 503
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{keycloak_realm_url}/.well-known/openid-configuration", timeout=5)
            resp.raise_for_status()
            oidc = resp.json()
    except Exception as exc:
        return {"error": str(exc)}, 502
    return {
        "issuer": oidc.get("issuer"),
        "authorization_endpoint": oidc.get("authorization_endpoint"),
        "token_endpoint": oidc.get("token_endpoint"),
        "token_endpoint_auth_methods_supported": oidc.get(
            "token_endpoint_auth_methods_supported", ["client_secret_post", "client_secret_basic"]
        ),
        "jwks_uri": oidc.get("jwks_uri"),
        # Advertise only the scopes the MCP server needs. Keycloak supports many
        # more (address, phone, roles, web-origins, etc.) but advertising them
        # causes clients to request them all, which Keycloak may reject or which
        # add unnecessary claims to tokens.
        "scopes_supported": ["openid", "profile", "email", "offline_access"],
        "response_types_supported": oidc.get("response_types_supported"),
        "grant_types_supported": oidc.get("grant_types_supported", ["authorization_code", "refresh_token"]),
        "code_challenge_methods_supported": ["S256"],
        "revocation_endpoint": oidc.get("revocation_endpoint"),
        # Omit registration_endpoint — clients should use the pre-registered
        # renku-mcp client rather than attempting dynamic client registration.
    }, 200


def _build_http_app(deps: MCPDependencies) -> Any:
    """Build the HTTP ASGI app with OAuth metadata endpoints and Bearer-token middleware.

    Routes and middleware are added directly to the FastMCP app so its lifespan
    (which initialises the task group) runs correctly under uvicorn.
    """
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request
    from starlette.responses import JSONResponse, Response

    base_url = deps.base_url
    keycloak_realm_url = _keycloak_issuer_url()

    @mcp.custom_route("/.well-known/oauth-protected-resource", methods=["GET"])  # type: ignore[misc]
    async def protected_resource_metadata(request: Request) -> JSONResponse:
        return JSONResponse(_protected_resource_doc(base_url, keycloak_realm_url))

    @mcp.custom_route("/.well-known/oauth-authorization-server", methods=["GET"])  # type: ignore[misc]
    async def authorization_server_metadata(request: Request) -> JSONResponse:
        body, status = await _authorization_server_doc(keycloak_realm_url)
        return JSONResponse(body, status_code=status)

    class _AuthMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next: Any) -> Response:
            # Metadata endpoints are public — no auth required.
            if request.url.path.startswith("/.well-known/"):
                return await call_next(request)
            # We extract the token here but do not validate it. Validation
            # happens implicitly downstream: if the token is invalid or expired,
            # the Renku data API returns a 401 when the tool calls deps.api().
            auth_header = request.headers.get("Authorization", "")
            token = auth_header.removeprefix("Bearer ").removeprefix("bearer ").strip()
            if not token:
                resource_metadata_url = f"{base_url}/.well-known/oauth-protected-resource"
                return Response(
                    status_code=401,
                    headers={"WWW-Authenticate": f'Bearer resource_metadata="{resource_metadata_url}"'},
                )
            set_current_token(token)
            return await call_next(request)

    # Add middleware directly to the FastMCP app — no outer wrapper so the
    # FastMCP lifespan (task group init) runs correctly under uvicorn.
    asgi_app = mcp.streamable_http_app()
    asgi_app.add_middleware(_AuthMiddleware)
    return asgi_app


# Module-level objects so `mcp dev` can discover the server by name.
_deps = MCPDependencies.from_env()

# In stdio mode, pass _resolve_token as a lazy resolver so the server picks up
# a fresh rnk login without needing a restart.
# In HTTP mode, the per-request middleware is the sole source of tokens.
_is_stdio = os.environ.get("MCP_TRANSPORT", "stdio") != "streamable-http"
_token_resolver: Callable[[], str] | None = _resolve_token if _is_stdio else None
mcp = create_server(_deps, token_resolver=_token_resolver)


async def _run_stdio() -> None:
    await mcp.run_stdio_async()


def _run_http() -> None:
    import uvicorn

    host = os.environ.get("MCP_HOST", "0.0.0.0")
    port = int(os.environ.get("MCP_PORT", "9000"))
    app = _build_http_app(_deps)
    logger.info("Starting Renku MCP server (HTTP) on %s:%s", host, port)
    uvicorn.run(app, host=host, port=port)


def main() -> None:
    """Start the MCP server using the transport configured via MCP_TRANSPORT env var."""
    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    if transport == "streamable-http":
        _run_http()
    else:
        asyncio.run(_run_stdio())


if __name__ == "__main__":
    main()
