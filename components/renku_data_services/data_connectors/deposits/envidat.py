"""Client for the Envidat deposit status API."""

import os
from enum import StrEnum, auto

import httpx
from pydantic import BaseModel

from renku_data_services.errors import errors


class EnvidatStatus(StrEnum):
    """Envidat statuses."""

    draft = auto()
    pending = auto()
    published = auto()


class EnvidatDepositStatus(BaseModel):
    """Status response from the Envidat deposit status endpoint."""

    package_id: str
    status: EnvidatStatus
    renku_id: str
    doi: str

    @property
    def is_published(self) -> bool:
        """Whether the deposit has been published on Envidat."""
        return self.status == EnvidatStatus.published


class EnvidatClient:
    """Client for interacting with the Envidat deposit status API."""

    def __init__(self) -> None:
        self.__base_url = os.environ.get("ENVIDAT_URL", "https://www.envidat.ch").rstrip("/")
        self.__client = httpx.AsyncClient(follow_redirects=True)

    async def get_deposit_status(self, renku_id: str) -> EnvidatDepositStatus:
        """Check the publication status of a deposit on Envidat."""
        url = f"{self.__base_url}/api/renku/{renku_id}/"
        res = await self.__client.get(url)
        if res.status_code == 404:
            raise errors.MissingResourceError(
                message=f"Envidat deposit with Renku ID '{renku_id}' was not found.",
            )
        if res.status_code >= 300 or res.status_code < 200:
            raise errors.ThirdPartyAPIError(
                message=f"Received unexpected status code {res.status_code} when checking Envidat deposit status.",
                detail=f"Message from Envidat: {res.text}",
            )
        return EnvidatDepositStatus.model_validate(res.json())
