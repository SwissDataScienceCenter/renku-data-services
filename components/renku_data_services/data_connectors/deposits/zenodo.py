"""Client for the Zenodo API."""

from datetime import datetime

import httpx
from pydantic import BaseModel, RootModel


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
        self.__zenodo_base_url = "https://zenodo.org/api"
        self.__client: httpx.AsyncClient

    async def create_deposit(self, api_key: str, title: str) -> DepositResponse:
        """Create a zenodo deposit."""
        header = {"Authorization": f"Bearer {api_key}"}
        res = await self.__client.post(
            self.__zenodo_base_url + "/deposit/depositions", json={"title": title}, headers=header
        )
        return DepositResponse.model_validate_json(res.json())

    async def get_deposit(self, api_key: str, id: int) -> DepositResponse:
        """Get a specific Zenodo deposit."""
        header = {"Authorization": f"Bearer {api_key}"}
        res = await self.__client.get(self.__zenodo_base_url + f"/deposit/depositions/{id}", headers=header)
        return DepositResponse.model_validate_json(res.json())

    async def get_deposits(self, api_key: str) -> DepositResponseList:
        """List Zenodo deposits."""
        header = {"Authorization": f"Bearer {api_key}"}
        res = await self.__client.get(self.__zenodo_base_url + "/deposit/depositions", headers=header)
        return DepositResponseList.model_validate_json(res.json())
