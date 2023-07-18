"""Keycloak user store."""
from dataclasses import dataclass
from typing import Dict, Optional, cast

import httpx
import renku_data_services.models.crc as models


@dataclass
class KcUserStore:
    """Wrapper around checking if users exist in Keycloak."""

    keycloak_url: str
    realm: str = "Renku"

    def __post_init__(self):
        self.keycloak_url = self.keycloak_url.rstrip("/")

    async def get_user_by_id(self, id: str, access_token: str) -> Optional[models.User]:
        """Get a user by their unique id."""
        url = f"{self.keycloak_url}/admin/realms/{self.realm}/users/{id}"
        async with httpx.AsyncClient() as client:
            res = await client.get(url=url, headers={"Authorization": f"bearer {access_token}"})
        if res.status_code == 200 and cast(Dict, res.json()).get("id") == id:
            return models.User(keycloak_id=id)
        return None
