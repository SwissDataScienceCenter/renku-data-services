import os
from datetime import datetime
from unittest.mock import patch

import pytest

from renku_data_services.data_connectors.deposits.scicat import ScicatAPIClient

TOKEN = os.environ.get("SCICAT_TOKEN", "secret-token")

client = ScicatAPIClient()


@pytest.mark.asyncio
async def test_create_deposit() -> None:
    # Create a deposit with minimal required fields
    user = {"email": "user@example.com", "full_name": "User Full Name"}

    deposit_data = {
        "contactEmail": user["email"],
        "creationTime": datetime.now().isoformat(),
        "datasetName": "dataset-1",
        "description": "",
        "owner": user["full_name"],
        "ownerEmail": user["email"],
        "ownerGroup": "psi-awi-m2",
        "sourceFolder": "/path/to/source/folder",
        "type": "base",
    }
    result = await client.create_deposit(api_key=TOKEN, data=deposit_data)

    assert result.datasetName == "dataset-1"


@pytest.mark.asyncio
async def test_get_deposit() -> None:
    # Test getting the deposit by ID
    deposit_id = "20.500.11935/759fa68c-808b-4107-9e9a-482bd2feb8cc"
    retrieved_deposit = await client.get_deposit(api_key=TOKEN, id=deposit_id)
    assert retrieved_deposit is not None


@pytest.mark.asyncio
async def test_get_user_groups() -> None:
    # Test getting the user's groups
    user_groups = await client.get_user_groups(api_key=TOKEN)
    assert isinstance(user_groups, list)


@pytest.mark.asyncio
@patch(
    "renku_data_services.data_connectors.deposits.scicat.ScicatAPIClient.get_user_identity",
    return_value={"profile": {"accessGroups": ["psi-awi-m2", "psi-awi-m3"]}},
)
async def test_get_user_groups_mocked_1(mock_get) -> None:
    # Test getting the user's groups with mocked response
    user_groups = await client.get_user_groups(api_key=TOKEN)
    assert len(user_groups) == 2
    assert user_groups[0] == "psi-awi-m2"
    assert user_groups[1] == "psi-awi-m3"


@pytest.mark.asyncio
@patch(
    "renku_data_services.data_connectors.deposits.scicat.ScicatAPIClient.get_user_identity",
    return_value={"profile": {"groups": []}},
)
async def test_get_user_groups_mocked_2(mock_get) -> None:
    # Test getting the user's groups with mocked response
    user_groups = await client.get_user_groups(api_key=TOKEN)
    assert len(user_groups) == 0


@pytest.mark.asyncio
async def test_get_scicat_token() -> None:
    # Test getting the SciCat token
    ACCESS_TOKEN = os.environ.get("ACCESS_TOKEN", "access-token")
    scicat_token = await client.get_scicat_token(access_token=ACCESS_TOKEN)
    assert len(scicat_token) > 0
