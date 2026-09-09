import os
from datetime import datetime

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
