"""An url referring to a git repository."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import ParseResult, urlparse

import httpx

from renku_data_services.app_config import logging

logger = logging.getLogger(__file__)


class GitUrlError(StrEnum):
    """Possible errors for testing an url string."""

    no_url_scheme = "no_url_scheme"
    no_url_host = "no_url_host"
    no_git_repo = "no_git_repo"
    no_url_path = "no_url_path"
    invalid_url_scheme = "invalid_url_scheme"
    invalid_git_url = "invalid_git_url"


@dataclass(frozen=True, eq=True, kw_only=True)
class GitUrl:
    """A url referring to a git repository."""

    parsed_url: ParseResult

    @classmethod
    def parse(cls, url: str) -> GitUrlError | GitUrl:
        """Parse a string into a GitUrl."""
        return cls.from_parsed(urlparse(url.strip()))

    @classmethod
    def from_parsed(cls, url: ParseResult) -> GitUrlError | GitUrl:
        """Tests a parsed url if it is a valid GitUrl."""

        if url.scheme == "":
            return GitUrlError.no_url_scheme
        if url.scheme not in ["http", "https"]:
            return GitUrlError.invalid_url_scheme
        if url.netloc == "":
            return GitUrlError.no_url_host
        # Don't allow localhost
        if url.netloc.startswith("localhost:") or url.netloc == "localhost":
            return GitUrlError.invalid_git_url
        if url.netloc.startswith("127.") or url.netloc.startswith("::1"):
            return GitUrlError.invalid_git_url

        # fix trailing slashes
        while url.path.endswith("/"):
            url = url._replace(path=url.path[:-1])

        return GitUrl(parsed_url=url)

    @classmethod
    def unsafe(cls, url: str) -> GitUrl:
        """Parses the url and raises errors."""
        match cls.parse(url):
            case GitUrl() as gu:
                return gu
            case GitUrlError() as err:
                raise Exception(f"Invalid git url ({err}): {url}")

    def render(self) -> str:
        """Return the url as a string."""
        return self.parsed_url.geturl()

    async def check_http_git_repository(self, client: httpx.AsyncClient) -> GitUrlError | None:
        """Whether this url is a http/https url to a git repository."""
        service_url = self.render() + "/info/refs?service=git-upload-pack"
        try:
            async with client.stream("GET", service_url, follow_redirects=True) as r:
                if r.status_code == 200:
                    return (
                        None
                        if bool(r.headers.get("Content-Type") == "application/x-git-upload-pack-advertisement")
                        else GitUrlError.no_git_repo
                    )
                else:
                    return GitUrlError.no_git_repo
        except httpx.HTTPError as err:
            logger.debug(f"Error accessing url for git repo check ({err}): {self}")
            return GitUrlError.no_git_repo

    def __str__(self) -> str:
        return self.render()
