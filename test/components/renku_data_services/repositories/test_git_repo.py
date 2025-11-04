"""Tests for the git_repo module."""

from httpx import AsyncClient
import pytest
from renku_data_services.repositories import git_repo


@pytest.mark.asyncio
async def test_check_url() -> None:
    test_url = "http://code.home/eikek/garmin"
    client = AsyncClient()
    url = git_repo.check_url_str(test_url).successOrRaise()
    code = await git_repo.check_git_repository(client, url)
    print("\n")
    print(code)
