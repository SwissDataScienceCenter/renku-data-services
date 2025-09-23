"""Test functions for the utils-http module."""

from collections.abc import Callable, Coroutine
from typing import Any

import pytest
from httpx import RequestError, Response

from renku_data_services.utils.http import HttpClient

client = HttpClient(timeout=2)

type RunRequest = Callable[[str], Coroutine[Any, Any, Response]]


async def expect_error(rr: RunRequest, url: str) -> RequestError:
    try:
        await rr(url)
        pytest.fail("Expected failure, but request was successful")
    except RequestError as e:
        return e


@pytest.mark.asyncio
async def test_add_url() -> None:
    urls = ["http://bad-label--.com", ""]
    methods: list[RunRequest] = [client.post, client.get, client.delete, client.patch, client.head, client.put]
    for m in methods:
        for url in urls:
            error = await expect_error(m, url)
            errm = f"url={url}"
            assert errm in str(error)
