"""Client for the SciCat API."""

import os
from urllib.parse import quote

import httpx
from pydantic import BaseModel

from renku_data_services.errors import errors


class DepositResponse(BaseModel):
    """Response from listing or creating a deposit in SciCat."""

    ownerGroup: str
    accessGroups: list
    owner: str
    ownerEmail: str
    contactEmail: str
    sourceFolder: str
    size: int
    packedSize: int
    numberOfFiles: int
    numberOfFilesArchived: int
    creationTime: str
    keywords: list[str]
    description: str
    datasetName: str
    classification: str
    isPublished: bool
    techniques: list
    sharedWith: list
    relationships: list
    datasetlifecycle: dict
    scientificMetadata: dict
    pid: str
    type: str
    version: str
    inputDatasets: list[str]
    usedSoftware: list[str]
    createdBy: str
    updatedBy: str
    createdAt: str
    updatedAt: str


class ScicatAPIClient:
    """SciCat API client."""

    def __init__(self) -> None:
        self.base_url = os.environ.get("SCICAT_API_URL", "https://dacat-qa.psi.ch/api/v3")  # TODO
        self.__client = httpx.AsyncClient()

    async def create_deposit(self, api_key: str, data: dict) -> DepositResponse:
        """Create a new deposit in SciCat."""
        header = {"Authorization": f"Bearer {api_key}"}
        res = await self.__client.post(f"{self.base_url}/datasets", headers=header, json=data)
        if res.status_code >= 300 or res.status_code < 200:
            raise errors.ThirdPartyAPIError(
                message=f"Received unexpected status code {res.status_code} when trying to create SciCat deposit.",
                detail=f"Message from SciCat: {res.text}",
            )
        return DepositResponse.model_validate(res.json())

    async def get_deposit(self, api_key: str, id: str) -> DepositResponse:
        """Get deposit information from SciCat."""
        header = {"Authorization": f"Bearer {api_key}"}
        res = await self.__client.get(f"{self.base_url}/datasets/{quote(id, safe='')}", headers=header)
        if res.status_code == 404:
            raise errors.MissingResourceError(
                message=f"SciCat deposit with ID '{id}' was not found.",
            )
        if res.status_code >= 300 or res.status_code < 200:
            raise errors.ThirdPartyAPIError(
                message=f"Received unexpected status code {res.status_code} when trying to get SciCat deposit.",
                detail=f"Message from SciCat: {res.text}",
            )
        return DepositResponse.model_validate(res.json())
