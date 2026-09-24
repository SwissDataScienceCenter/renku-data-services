from unittest.mock import patch

import httpx
import pytest

from renku_data_services.data_connectors.apispec import DepositPost, DepositProvider
from renku_data_services.data_connectors.deposits.scicat import ScicatAPIClient, UserProfile, UserResponse
from renku_data_services.errors import errors

DATA_CONNECTOR_ID = "01ARZ3NDEKTSV4RRFFQ69G5FAV"


def make_deposit_post(path: str | None = "/some/path") -> DepositPost:
    return DepositPost(
        name="my deposit", provider=DepositProvider.scicat, data_connector_id=DATA_CONNECTOR_ID, path=path
    )


def make_user_identity_json(access_groups: list[str]) -> dict:
    return {"profile": {"displayName": "Jane Doe", "email": "jane.doe@example.com", "accessGroups": access_groups}}


def make_deposit_json(pid: str = "some-pid") -> dict:
    return {
        "ownerGroup": "group1",
        "owner": "Jane Doe",
        "ownerEmail": "jane.doe@example.com",
        "contactEmail": "jane.doe@example.com",
        "sourceFolder": "/some/path",
        "creationTime": "2026-09-23T00:00:00",
        "description": "",
        "datasetName": "my deposit",
        "isPublished": False,
        "pid": pid,
        "type": "base",
    }


@pytest.mark.asyncio
@patch(
    "renku_data_services.data_connectors.deposits.scicat.httpx.AsyncClient.get",
    return_value=httpx.Response(200, json=make_user_identity_json(["group1", "group2"])),
)
async def test_get_user_identity(mock_get) -> None:
    client = ScicatAPIClient()
    result = await client.get_user_identity("some-token")
    assert result == UserResponse(
        profile=UserProfile(displayName="Jane Doe", email="jane.doe@example.com", accessGroups=["group1", "group2"])
    )


@pytest.mark.asyncio
@patch(
    "renku_data_services.data_connectors.deposits.scicat.httpx.AsyncClient.get",
    return_value=httpx.Response(500, text="internal error"),
)
async def test_get_user_identity_error(mock_get) -> None:
    client = ScicatAPIClient()
    with pytest.raises(errors.ThirdPartyAPIError):
        await client.get_user_identity("some-token")


@pytest.mark.asyncio
@patch(
    "renku_data_services.data_connectors.deposits.scicat.httpx.AsyncClient.get",
    return_value=httpx.Response(200, json=make_user_identity_json(["group1", "group2"])),
)
async def test_default_deposit_data_uses_first_access_group(mock_get) -> None:
    client = ScicatAPIClient()
    data = await client.default_deposit_data("some-token", make_deposit_post())
    assert data["ownerGroup"] == "group1"
    assert data["datasetName"] == "my deposit"
    assert data["sourceFolder"] == "/some/path"


@pytest.mark.asyncio
@patch(
    "renku_data_services.data_connectors.deposits.scicat.httpx.AsyncClient.get",
    return_value=httpx.Response(200, json=make_user_identity_json([])),
)
async def test_default_deposit_data_no_access_groups(mock_get) -> None:
    client = ScicatAPIClient()
    data = await client.default_deposit_data("some-token", make_deposit_post(path=None))
    assert data["ownerGroup"] == ""
    assert data["sourceFolder"] == ""


@pytest.mark.asyncio
@patch(
    "renku_data_services.data_connectors.deposits.scicat.httpx.AsyncClient.post",
    return_value=httpx.Response(200, json=make_deposit_json(pid="new-pid")),
)
@patch(
    "renku_data_services.data_connectors.deposits.scicat.httpx.AsyncClient.get",
    return_value=httpx.Response(200, json=make_user_identity_json(["group1"])),
)
async def test_create_deposit(mock_get, mock_post) -> None:
    client = ScicatAPIClient()
    result = await client.create_deposit("some-token", make_deposit_post())
    assert result.pid == "new-pid"


@pytest.mark.asyncio
@patch(
    "renku_data_services.data_connectors.deposits.scicat.httpx.AsyncClient.post",
    return_value=httpx.Response(400, text="bad request"),
)
@patch(
    "renku_data_services.data_connectors.deposits.scicat.httpx.AsyncClient.get",
    return_value=httpx.Response(200, json=make_user_identity_json(["group1"])),
)
async def test_create_deposit_error(mock_get, mock_post) -> None:
    client = ScicatAPIClient()
    with pytest.raises(errors.ThirdPartyAPIError):
        await client.create_deposit("some-token", make_deposit_post())


@pytest.mark.asyncio
@patch(
    "renku_data_services.data_connectors.deposits.scicat.httpx.AsyncClient.get",
    return_value=httpx.Response(200, json=make_deposit_json(pid="existing-pid")),
)
async def test_get_deposit(mock_get) -> None:
    client = ScicatAPIClient()
    result = await client.get_deposit("some-token", "existing-pid")
    assert result.pid == "existing-pid"


@pytest.mark.asyncio
@patch(
    "renku_data_services.data_connectors.deposits.scicat.httpx.AsyncClient.get",
    return_value=httpx.Response(404, text="not found"),
)
async def test_get_deposit_not_found(mock_get) -> None:
    client = ScicatAPIClient()
    with pytest.raises(errors.MissingResourceError):
        await client.get_deposit("some-token", "missing-pid")


@pytest.mark.asyncio
@patch(
    "renku_data_services.data_connectors.deposits.scicat.httpx.AsyncClient.get",
    return_value=httpx.Response(500, text="internal error"),
)
async def test_get_deposit_error(mock_get) -> None:
    client = ScicatAPIClient()
    with pytest.raises(errors.ThirdPartyAPIError):
        await client.get_deposit("some-token", "some-pid")


@pytest.mark.asyncio
@patch(
    "renku_data_services.data_connectors.deposits.scicat.httpx.AsyncClient.post",
    return_value=httpx.Response(200, json={"access_token": "the-scicat-token"}),
)
async def test_get_scicat_token(mock_post) -> None:
    client = ScicatAPIClient()
    token = await client.get_scicat_token("some-access-token")
    assert token == "the-scicat-token"


@pytest.mark.asyncio
@patch(
    "renku_data_services.data_connectors.deposits.scicat.httpx.AsyncClient.post",
    return_value=httpx.Response(401, text="unauthorized"),
)
async def test_get_scicat_token_error(mock_post) -> None:
    client = ScicatAPIClient()
    with pytest.raises(errors.ThirdPartyAPIError):
        await client.get_scicat_token("some-access-token")


@pytest.mark.asyncio
@patch(
    "renku_data_services.data_connectors.deposits.scicat.httpx.AsyncClient.post",
    return_value=httpx.Response(200, json={"token_type": "bearer"}),
)
async def test_get_scicat_token_missing_access_token(mock_post) -> None:
    client = ScicatAPIClient()
    with pytest.raises(errors.ThirdPartyAPIError):
        await client.get_scicat_token("some-access-token")
