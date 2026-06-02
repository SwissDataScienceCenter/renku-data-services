"""Entrypoint for the Renku MCP server.

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
import os
import sys
import time
from pathlib import Path
from typing import Any

import logging

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


def _build_http_app(deps: MCPDependencies):  # type: ignore[return]
    """Wrap the FastMCP ASGI app with per-request Bearer-token auth middleware."""
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request
    from starlette.responses import Response

    class _AuthMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next: Any) -> Response:
            # Token validation is handled by the ingress proxy, same as the
            # rest of the data service. We just extract and forward the token.
            auth_header = request.headers.get("Authorization", "")
            token = auth_header.removeprefix("Bearer ").removeprefix("bearer ").strip()
            set_current_token(token)
            return await call_next(request)

    asgi_app = mcp.streamable_http_app()
    asgi_app.add_middleware(_AuthMiddleware)  # type: ignore[attr-defined]
    return asgi_app


# Module-level objects so `mcp dev` can discover the server by name.
_deps = MCPDependencies.from_env()
mcp = create_server(_deps)

# Resolve and seed the token at import time only for stdio mode.
# In HTTP mode the per-request middleware is the sole source of tokens —
# seeding here would create a process-wide default that could leak across
# requests if the middleware ever failed to run.
if os.environ.get("MCP_TRANSPORT", "stdio") != "streamable-http":
    try:
        _resolved_token = _resolve_token()
    except RuntimeError as exc:
        logger.warning("Could not resolve a Renku token: %s", exc)
        _resolved_token = ""
    if not _resolved_token:
        logger.warning("No token found — most tools will return permission errors.")
    set_current_token(_resolved_token)


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
    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    if transport == "streamable-http":
        _run_http()
    else:
        asyncio.run(_run_stdio())


if __name__ == "__main__":
    main()
