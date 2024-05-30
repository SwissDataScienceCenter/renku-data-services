"""Utilities for connected services."""

import base64
import random

import httpx


def generate_code_verifier(size: int = 48) -> str:
    """Returns a randomly generated code for use in PKCE."""
    rand = random.SystemRandom()
    return base64.b64encode(rand.randbytes(size)).decode()


async def probe_repository(repository_url: str) -> bool:
    """Probe a repository to check if it is publicly available."""
    async with httpx.AsyncClient() as client:
        url = f"{repository_url}/info/refs?service=git-upload-pack"
        res = await client.get(url=url)
        if res.status_code != 200:
            return False
        return bool(res.headers.get("Content-Type") == "application/x-git-upload-pack-advertisement")
