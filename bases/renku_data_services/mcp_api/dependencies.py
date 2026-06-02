"""Dependency container for the MCP server — just a base URL and an HTTP client."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass
class MCPDependencies:
    base_url: str

    @classmethod
    def from_env(cls) -> MCPDependencies:
        base_url = os.environ.get("RENKU_BASE_URL", "https://renkulab.io").rstrip("/")
        return cls(base_url=base_url)

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
        """Make an authenticated call to the Renku data API."""
        url = f"{self.base_url}/api/data{path}"
        params = {k: str(v) for k, v in (query or {}).items() if v is not None}
        headers: dict[str, str] = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if extra_headers:
            headers.update(extra_headers)

        async with httpx.AsyncClient() as client:
            resp = await client.request(
                method,
                url,
                params=params or None,
                content=json.dumps(body).encode() if body is not None else None,
                headers=headers,
            )
            try:
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise RuntimeError(f"HTTP {exc.response.status_code}: {exc.response.text}") from exc

            result = resp.json() if resp.content else None
            if return_headers:
                return result, dict(resp.headers)
            return result
