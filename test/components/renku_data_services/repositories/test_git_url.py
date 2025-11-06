"""Tests for the git_url module."""

import pytest
from httpx import AsyncClient

from renku_data_services.repositories.git_url import GitUrl, GitUrlError


def test_bad_urls() -> None:
    bad_urls = ["", "abc", "http://", "localhost/repo", "ftp://test.com", "http://github.com"]
    for url in bad_urls:
        result = GitUrl.parse(url)
        assert isinstance(result, GitUrlError)


def test_good_urls() -> None:
    good_urls = ["http://localhost:3000/my/repo", "https://github.com/SwissDataScienceCenter/renku"]
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
