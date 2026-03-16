"""Client for the Zenodo API."""

import os
from datetime import datetime

import httpx
from pydantic import BaseModel, RootModel

from renku_data_services.errors import errors


class DepositResponse(BaseModel):
    """Response from listing or creating a deposit in zenodo."""

    created: datetime
    id: int
    links: dict[str, str]
    state: str
    submitted: bool
    title: str
    owner: int


class DepositResponseList(RootModel[list[DepositResponse]]):
    """List of deposits."""

    root: list[DepositResponse]


class ZenodoAPIClient:
    """Client to deal with Zenodo datasets."""

    def __init__(self) -> None:
        self.__zenodo_base_url = os.environ.get("ZENODO_URL", "https://zenodo.org").rstrip("/") + "/api"
        self.__client = httpx.AsyncClient()

    async def create_deposit(self, api_key: str, title: str) -> DepositResponse:
        """Create a zenodo deposit."""
        header = {"Authorization": f"Bearer {api_key}"}
        payload = {"metadata": {"title": title, "upload_type": "dataset"}}
        res = await self.__client.post(self.__zenodo_base_url + "/deposit/depositions", headers=header, json=payload)
        if res.status_code >= 300 or res.status_code < 200:
            raise errors.ThirdPartyAPIError(
                message=f"Received unexpected status code {res.status_code} when trying to create zenodo deposit.",
                detail=f"Message from zenodo: {res.text[:100]}",
            )
        return DepositResponse.model_validate(res.json())

    async def get_deposit(self, api_key: str, id: int) -> DepositResponse:
        """Get a specific Zenodo deposit."""
        header = {"Authorization": f"Bearer {api_key}"}
        res = await self.__client.get(self.__zenodo_base_url + f"/deposit/depositions/{id}", headers=header)
        if res.status_code >= 300 or res.status_code < 200:
            raise errors.ThirdPartyAPIError(
                message=f"Received unexpected status code {res.status_code} when trying to get zenodo deposit.",
                detail=f"Message from zenodo: {res.text[:100]}",
            )
        return DepositResponse.model_validate(res.json())

    async def get_deposits(self, api_key: str) -> DepositResponseList:
        """List Zenodo deposits."""
        header = {"Authorization": f"Bearer {api_key}"}
        res = await self.__client.get(self.__zenodo_base_url + "/deposit/depositions", headers=header)
        if res.status_code >= 300 or res.status_code < 200:
            raise errors.ThirdPartyAPIError(
                message=f"Received unexpected status code {res.status_code} when trying to list zenodo deposits.",
                detail=f"Message from zenodo: {res.text[:100]}",
            )
        return DepositResponseList.model_validate(res.json())
