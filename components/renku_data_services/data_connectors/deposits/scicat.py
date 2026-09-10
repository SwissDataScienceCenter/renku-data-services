"""Client for the SciCat API."""

import os
from typing import cast
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

    async def get_user_identity(self, api_key: str) -> dict:
        """Get the user's identity in SciCat."""
        header = {"Authorization": f"Bearer {api_key}"}
        res = await self.__client.get(f"{self.base_url}/users/my/identity", headers=header)
        if res.status_code >= 300 or res.status_code < 200:
            raise errors.ThirdPartyAPIError(
                message=f"Received unexpected status code {res.status_code} when trying to get SciCat user identity.",
                detail=f"Message from SciCat: {res.text}",
            )
        return cast(dict, res.json())

    async def get_user_groups(self, api_key: str) -> list[str]:
        """Get the groups the user belongs to in SciCat."""
        res_json = await self.get_user_identity(api_key)
        return cast(list[str], res_json.get("profile", {}).get("accessGroups", []))

    async def get_scicat_token(self, access_token: str) -> str:
        """Get the SciCat API token for a user."""
        res = await self.__client.post(f"{self.base_url}/auth/oidc/token", data={"idToken": access_token})
        if res.status_code >= 300 or res.status_code < 200:
            raise errors.ThirdPartyAPIError(
                message=f"Received unexpected status code {res.status_code} when trying to get SciCat token.",
                detail=f"Message from SciCat: {res.text}",
            )
        if "access_token" not in res.json():
            raise errors.ThirdPartyAPIError(
                message="SciCat token response did not contain an access_token.",
                detail=f"Message from SciCat: {res.text}",
            )
        return cast(str, res.json().get("access_token"))
