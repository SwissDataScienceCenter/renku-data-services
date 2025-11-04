"""Functions for git repo urls."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Callable
from urllib.parse import ParseResult, urlparse

from httpx import AsyncClient
import httpx

type GitUrl = ParseResult


class CheckUrlError(StrEnum):
    """Possible errors for testing an url string."""

    no_scheme = "no_scheme"
    no_host = "no_host"
    no_git_repo = "no_git_repo"


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
        return CheckUrlResult(url, CheckUrlError.no_scheme)
    if parsed_url.netloc == "":
        return CheckUrlResult(url, CheckUrlError.no_host)

    ## todo : more tests - i.e. which protocols do we support?
    return CheckUrlResult(url, parsed_url)


async def check_git_repository(client: AsyncClient, url: GitUrl) -> CheckUrlResult:
    """Tries to determine, whether the given url is a git repository."""
    service_url = url.geturl() + "/info/refs?service=git-upload-pack"
    with httpx.stream("GET", service_url) as r:
        if r.status_code == 200:
            return CheckUrlResult(url.geturl(), url)
        else:
            return CheckUrlResult(url.geturl(), CheckUrlError.no_git_repo)
