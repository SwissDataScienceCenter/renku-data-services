"""Functions for git repo urls."""

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import ParseResult, urlparse

import httpx
from httpx import AsyncClient

from renku_data_services.app_config import logging

logger = logging.getLogger(__file__)

type GitUrl = ParseResult


class CheckUrlError(StrEnum):
    """Possible errors for testing an url string."""

    no_url_scheme = "no_scheme"
    no_url_host = "no_host"
    no_git_repo = "no_git_repo"
    invalid_url_scheme = "invalid_url_scheme"
    metadata_unauthorized = "metadata_unauthorized"
    metadata_unknown = "metadata_unknown_error"


@dataclass
class CheckUrlResult:
    """Result of checking an url."""

    input: str
    value: GitUrl | CheckUrlError

    def fold[A](self, fa: Callable[[GitUrl], A], fb: Callable[[CheckUrlError], A]) -> A:
        """Runs one of the given functions corresponding to this result."""
        match self.value:
            case ParseResult() as url:
                return fa(url)
            case CheckUrlError() as err:
                return fb(err)

    def get_error(self) -> CheckUrlError | None:
        """Return the error if applicable."""
        return self.fold(lambda _: None, lambda e: e)

    @property
    def is_error(self) -> bool:
        """Return whether this is an error result."""
        return self.fold(lambda _: False, lambda _: True)

    @property
    def is_success(self) -> bool:
        """Return whether this is a success response."""
        return not self.is_error

    def successOrRaise(self) -> GitUrl:
        """Return the value or raise an error."""
        match self.value:
            case ParseResult() as url:
                return url
            case CheckUrlError() as err:
                raise Exception(f"Error in git url '{self.input}': {err}")


def check_url_str(url: str) -> CheckUrlResult:
    """Checks a str for looking like a url."""
    parsed_url = urlparse(url)

    if parsed_url.scheme == "":
        return CheckUrlResult(url, CheckUrlError.no_url_scheme)
    if parsed_url.netloc == "":
        return CheckUrlResult(url, CheckUrlError.no_url_host)
    if parsed_url.scheme not in ["http", "https"]:
        return CheckUrlResult(url, CheckUrlError.invalid_url_scheme)

    ## todo : more tests - i.e. which protocols do we support?
    return CheckUrlResult(url, parsed_url)


async def check_git_repository(client: AsyncClient, url: GitUrl) -> CheckUrlResult:
    """Tries to determine, whether the given url is a git repository."""
    service_url = url.geturl() + "/info/refs?service=git-upload-pack"
    try:
        async with client.stream("GET", service_url) as r:
            if r.status_code == 200:
                return CheckUrlResult(url.geturl(), url)
            else:
                return CheckUrlResult(url.geturl(), CheckUrlError.no_git_repo)
    except httpx.TransportError:
        logger.debug(f"Error accessing url for git repo check: {url.geturl()}")
        return CheckUrlResult(url.geturl(), CheckUrlError.no_git_repo)
