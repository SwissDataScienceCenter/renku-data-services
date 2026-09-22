"""HTTP client for the Renku data API."""

from __future__ import annotations

import json
import os
from typing import Any, NamedTuple

import httpx

DEFAULT_TIMEOUT = 30.0


class ApiResponse(NamedTuple):
    """A data API response where more than the body matters."""

    body: Any
    status: int
    headers: dict[str, str]


class RenkuApiClient:
    """Calls the Renku data API on behalf of the user whose token is supplied per request.

    No token validation happens here — the data API is the authoritative validator
    (signature, issuer, expiry). An invalid token simply produces a 401 from the API,
    which is surfaced to the caller as a RuntimeError carrying the response body so
    the agent can act on the message.
    """

    def __init__(self, base_url: str, timeout: float = DEFAULT_TIMEOUT) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    @classmethod
    def from_env(cls) -> RenkuApiClient:
        """Build a client for the deployment named by RENKU_BASE_URL."""
        return cls(base_url=os.environ.get("RENKU_BASE_URL", "https://renkulab.io"))

    async def request(
        self,
        method: str,
        path: str,
        token: str,
        body: Any = None,
        *,
        query: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
        full_response: bool = False,
    ) -> Any:
        """Make an authenticated call to the Renku data API.

        Returns the parsed body, or an ApiResponse when full_response is set — needed where
        the status code or a header carries meaning the body does not, such as 201 vs 200 on
        POST /sessions, or an ETag required for a subsequent PATCH.
        """
        url = f"{self.base_url}/api/data{path}"
        params = {k: str(v) for k, v in (query or {}).items() if v is not None}
        headers: dict[str, str] = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if extra_headers:
            headers.update(extra_headers)

        async with httpx.AsyncClient(timeout=self.timeout) as client:
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
            if full_response:
                return ApiResponse(body=result, status=resp.status_code, headers=dict(resp.headers))
            return result
