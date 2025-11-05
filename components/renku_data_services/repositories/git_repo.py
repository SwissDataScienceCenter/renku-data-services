"""Functions for git repo urls."""

from __future__ import annotations

from enum import StrEnum
from urllib.parse import ParseResult, urlparse

import httpx
from httpx import AsyncClient

from renku_data_services.app_config import logging

logger = logging.getLogger(__file__)

type GitUrl = ParseResult


class RepositoryError(StrEnum):
    """Possible errors for testing an url string."""

    no_url_scheme = "no_scheme"
    no_url_host = "no_host"
    no_git_repo = "no_git_repo"
    invalid_url_scheme = "invalid_url_scheme"
    metadata_unauthorized = "metadata_unauthorized"
    metadata_unknown = "metadata_unknown_error"


def check_url_str(url: str) -> GitUrl | RepositoryError:
    """Checks a str for looking like a url."""
    parsed_url = urlparse(url)

    if parsed_url.scheme == "":
        return RepositoryError.no_url_scheme
    if parsed_url.netloc == "":
        return RepositoryError.no_url_host
    if parsed_url.scheme not in ["http", "https"]:
        return RepositoryError.invalid_url_scheme

    return parsed_url


async def check_git_repository(client: AsyncClient, url: GitUrl) -> RepositoryError | None:
    """Tries to determine, whether the given url is a git repository."""
    service_url = url.geturl() + "/info/refs?service=git-upload-pack"
    try:
        async with client.stream("GET", service_url) as r:
            if r.status_code == 200:
                return None
            else:
                return RepositoryError.no_git_repo
    except httpx.TransportError:
        logger.debug(f"Error accessing url for git repo check: {url.geturl()}")
        return RepositoryError.no_git_repo
