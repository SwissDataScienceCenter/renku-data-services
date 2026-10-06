"""HTTP client for the Renku data API."""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

DEFAULT_TIMEOUT = 30.0


class ApiError(RuntimeError):
    """A call to the data API failed.

    Exists for the message rather than the type: httpx reports a failed status as
    "Client error '404 Not Found' for url '...'" with a link to MDN and no response body,
    and a transport failure as a bare ConnectError. Both end up in an agent's context, so
    they are restated here with the API's own error text, which is the part worth reading.
    """


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

    def _http_client(self) -> httpx.AsyncClient:
        """An httpx client pointed at the data API, so callers pass only a path.

        A new one per request, as everywhere else in this repository that calls out over
        HTTP. It carries no credentials: the server handles one user per request, so the
        Authorization header is supplied at the call rather than baked in here.
        """
        return httpx.AsyncClient(
            base_url=f"{self.base_url}/api/data",
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            timeout=self.timeout,
        )

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

        Returns the parsed body, or the httpx response itself when full_response is set —
        needed where the status code or a header carries meaning the body does not, such as
        201 vs 200 on POST /sessions, or an ETag required for a subsequent PATCH.
        """
        params = {k: str(v) for k, v in (query or {}).items() if v is not None}
        # Only the caller's identity varies per request; everything else belongs on the client.
        headers = {"Authorization": f"Bearer {token}", **(extra_headers or {})}

        async with self._http_client() as client:
            try:
                resp = await client.request(
                    method,
                    path,
                    params=params or None,
                    content=json.dumps(body).encode() if body is not None else None,
                    headers=headers,
                )
            except httpx.RequestError as exc:
                # No response at all — a timeout, DNS failure, refused connection.
                raise ApiError(f"Could not reach the Renku data API: {exc}") from exc
            try:
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise ApiError(f"HTTP {exc.response.status_code}: {exc.response.text}") from exc

            if full_response:
                return resp
            return resp.json() if resp.content else None
