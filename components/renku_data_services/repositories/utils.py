"""Utilities for connected services."""

import httpx

from renku_data_services.repositories.git_url import GitUrl, GitUrlError


async def probe_repository(repository_url: str) -> bool:
    """Probe a repository to check if it is publicly available."""
    match GitUrl.parse(repository_url):
        case GitUrl() as url:
            async with httpx.AsyncClient(timeout=5) as client:
                result = await url.check_http_git_repository(client)
                return result is None
        case GitUrlError():
            return False
