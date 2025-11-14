"""Tests for the git_url module."""

import pytest
from httpx import AsyncClient

from renku_data_services.repositories.git_url import GitUrl, GitUrlError

bad_urls = [
    "",
    "abc",
    "http://",
    "localhost/repo",
    "ftp://test.com",
    "http://github.com",
    "http://localhost:3000/my/repo",
    "http://127.0.0.1:3000/my/repo",
    "http://127.0.0.1/my/repo",
    "http://localhost/my/repo",
]
good_urls = ["https://github.com/SwissDataScienceCenter/renku", "http://random/the/repo.git"]


def test_bad_urls() -> None:
    for url in bad_urls:
        result = GitUrl.parse(url)
        assert isinstance(result, GitUrlError)


def test_good_urls() -> None:
    for url in good_urls:
        result = GitUrl.parse(url)
        assert isinstance(result, GitUrl)


@pytest.mark.asyncio
async def test_check_http_repo() -> None:
    good_url = GitUrl.unsafe("https://github.com/SwissDataScienceCenter/renku")
    bad_url = GitUrl.unsafe("https://github.com/SwissDataScienceCenter")
    async with AsyncClient() as client:
        code_good = await good_url.check_http_git_repository(client)
        code_bad = await bad_url.check_http_git_repository(client)

    assert code_good is None, f"Unexpected error testing {good_url}: {code_good}"
    assert code_bad == GitUrlError.no_git_repo, f"Unexpected success testing {bad_url}"


def test_remove_trailing_slashes() -> None:
    urls = [
        "http://github.com/SwissDataScienceCenter/renku",
        "http://github.com/SwissDataScienceCenter/renku/",
        "http://github.com/SwissDataScienceCenter/renku//",
        "http://github.com/SwissDataScienceCenter/renku///",
        "http://github.com/SwissDataScienceCenter/renku////",
    ]
    for url in urls:
        git_url = GitUrl.unsafe(url)
        assert git_url.render() == "http://github.com/SwissDataScienceCenter/renku"


def test_strip_url() -> None:
    urls = [
        "  http://github.com/SwissDataScienceCenter/renku  ",
        "  http://github.com/SwissDataScienceCenter/renku/",
        "http://github.com/SwissDataScienceCenter/renku  ",
    ]
    for url in urls:
        git_url = GitUrl.unsafe(url)
        assert git_url.render() == "http://github.com/SwissDataScienceCenter/renku"
