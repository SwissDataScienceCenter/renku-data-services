"""Functions for checking access to images.

Access to docker images can fall into these cases:

1. The image is public and exists. It can be accessed anonymously
2. The image cannot be found. It may be absent or it requires credentials to access it

For the latter case, try to find out as much as possible:
- Look for credentials in the connected services
- If there are no connections defined for that user and registry, image is not accessible
- Try access it with the credentials, if it still fails the token could be invalid.
- Try to obtain the connected account that checks the token validity
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import final

import httpx

from renku_data_services.app_config import logging
from renku_data_services.base_models.core import APIUser
from renku_data_services.connected_services.db import ConnectedServicesRepository
from renku_data_services.connected_services.models import ImageProvider, OAuth2Client, OAuth2Connection
from renku_data_services.errors import errors
from renku_data_services.notebooks.api.classes.image import Image, ImageRepoDockerAPI

logger = logging.getLogger(__name__)


@final
@dataclass(frozen=True)
class CheckResult:
    """Result of checking access to an image."""

    accessible: bool
    response_code: int
    image_provider: ImageProvider | None = None
    token: str | None = field(default=None, repr=False)
    error: errors.UnauthorizedError | None = None

    def __str__(self) -> str:
        provider = "None"
        if self.client:
            conn = f"connection={self.connection.id}" if self.connection else "connection=None"
            provider = f"{self.client.id}/{self.client.kind} ({conn})"
        token = "***" if self.token else "None"
        error = "unauthorized" if self.error else "None"
        return (
            "CheckResult("
            f"accessible={self.accessible}/{self.response_code}, "
            f"provider={provider}, token={token}, error={error})"
        )

    @property
    def connection(self) -> OAuth2Connection | None:
        """Return the connection if present."""
        if self.image_provider is None:
            return None
        if self.image_provider.connected_user is None:
            return None
        return self.image_provider.connected_user.connection

    @property
    def client(self) -> OAuth2Client | None:
        """Return the OAuth2 client if present."""
        if self.image_provider is None:
            return None
        return self.image_provider.provider

    @property
    def user(self) -> APIUser | None:
        """Return the connected user if applicable."""
        if self.image_provider is None:
            return None
        if self.image_provider.connected_user is None:
            return None
        return self.image_provider.connected_user.user


async def check_image_path(
    image_path: str, user: APIUser, connected_services: ConnectedServicesRepository
) -> CheckResult:
    """Check access to the given image."""
    image = Image.from_path(image_path)
    return await check_image(image, user, connected_services)


async def check_image(image: Image, user: APIUser, connected_services: ConnectedServicesRepository) -> CheckResult:
    """Check access to the given image."""

    reg_api: ImageRepoDockerAPI = image.repo_api()  # public images
    unauth_error: errors.UnauthorizedError | None = None
    image_provider = await connected_services.get_provider_for_image(user, image)
    connected_user = image_provider.connected_user if image_provider is not None else None
    connection = connected_user.connection if connected_user is not None else None
    if image_provider is not None:
        try:
            reg_api = await connected_services.get_image_repo_client(image_provider)
        except errors.UnauthorizedError as e:
            logger.info(f"Error getting image repo client for image {image}: {e}")
            unauth_error = e

    try:
        result = await reg_api.image_check(image)
    except httpx.HTTPError as e:
        logger.info(f"Error connecting {reg_api.scheme}://{reg_api.hostname}: {e}")
        result = 0

    if result != 200 and connection is not None:
        try:
            await connected_services.get_oauth2_connected_account(connection.id, user)
        except errors.UnauthorizedError as e:
            logger.info(f"Error getting connected account: {e}")
            unauth_error = e

    return CheckResult(
        accessible=result == 200,
        response_code=result,
        image_provider=image_provider,
        token=reg_api.oauth2_token,
        error=unauth_error,
    )
