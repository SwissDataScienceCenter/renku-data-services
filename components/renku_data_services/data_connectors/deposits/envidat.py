"""Client for the Envidat deposit status API."""

import httpx
from pydantic import BaseModel

from renku_data_services.errors import errors


class EnvidatDepositStatus(BaseModel):
    """Status response from the Envidat deposit status endpoint."""

    status: str  # Published or Pending

    @property
    def is_published(self) -> bool:
        """Whether the deposit has been published on Envidat."""
        return self.status.lower() == "published"


class EnvidatClient:
    """Client for interacting with the Envidat deposit status API."""

    def __init__(self) -> None:
        self.__base_url = "https://www.envidat.ch"
        self.__client = httpx.AsyncClient()

    async def get_deposit_status(self, deposit_ulid: str) -> EnvidatDepositStatus:
        """Check the publication status of a deposit on Envidat."""
        url = f"{self.__base_url}/upload/{deposit_ulid}/status"
        res = await self.__client.get(url)
        if res.status_code >= 300 or res.status_code < 200:
            raise errors.ThirdPartyAPIError(
                message=f"Received unexpected status code {res.status_code} when checking Envidat deposit status.",
                detail=f"Message from Envidat: {res.text[:100]}",
            )
        return EnvidatDepositStatus.model_validate(res.json())
