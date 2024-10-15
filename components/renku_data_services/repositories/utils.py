"""Utilities for connected services."""

import httpx


async def probe_repository(repository_url: str) -> bool:
    """Probe a repository to check if it is publicly available."""
    async with httpx.AsyncClient() as client:
        url = f"{repository_url}/info/refs?service=git-upload-pack"
        res = await client.get(url=url, follow_redirects=True)
        if res.status_code != 200:
            return False
        return bool(res.headers.get("Content-Type") == "application/x-git-upload-pack-advertisement")
