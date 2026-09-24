"""Client for the SciCat API."""

import os
from datetime import datetime
from typing import cast
from urllib.parse import quote

import httpx
from pydantic import BaseModel

from renku_data_services.data_connectors.apispec import DepositPost
from renku_data_services.errors import errors

# See: https://dacat.psi.ch/explorer (prod) or https://dacat-qa.psi.ch/explorer (qa) for SciCat API documentation.


class DepositResponse(BaseModel):
    """Simplified response from listing or creating a deposit in SciCat."""

    ownerGroup: str
    owner: str
    ownerEmail: str
    contactEmail: str
    sourceFolder: str
    creationTime: str
    description: str
    datasetName: str
    isPublished: bool
    pid: str
    type: str


class UserProfile(BaseModel):
    """Simplified User Profile from user identity endpoint in SciCat."""

    displayName: str
    email: str
    accessGroups: list[str]


class UserResponse(BaseModel):
    """Simplified Response from user identity endpoint in SciCat."""

    profile: UserProfile


class ScicatAPIClient:
    """SciCat API client."""

    def __init__(self) -> None:
        self.base_url = os.environ.get("SCICAT_API_URL", "https://dacat.psi.ch/api/v3").rstrip("/")
        self.__client = httpx.AsyncClient()

    async def create_deposit(self, api_key: str, body: DepositPost) -> DepositResponse:
        """Create a new deposit in SciCat."""
        data = await self.default_deposit_data(api_key, body)
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

    async def get_user_identity(self, api_key: str) -> UserResponse:
        """Get the user's identity in SciCat."""
        header = {"Authorization": f"Bearer {api_key}"}
        res = await self.__client.get(f"{self.base_url}/users/my/identity", headers=header)
        if res.status_code >= 300 or res.status_code < 200:
            raise errors.ThirdPartyAPIError(
                message=f"Received unexpected status code {res.status_code} when trying to get SciCat user identity.",
                detail=f"Message from SciCat: {res.text}",
            )
        return UserResponse.model_validate(res.json())

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

    async def default_deposit_data(self, api_key: str, body: DepositPost) -> dict:
        """Get the default deposit data for a SciCat user."""
        user_identity = await self.get_user_identity(api_key)
        user = user_identity.profile
        user_groups = user.accessGroups
        return {
            "contactEmail": user.email,
            "owner": user.displayName,
            "ownerEmail": user.email,
            "ownerGroup": user_groups[0] if user_groups else "",
            "creationTime": datetime.now().isoformat(),
            "datasetName": body.name,
            "description": "",
            "sourceFolder": body.path or "",
            "type": "base",
        }
