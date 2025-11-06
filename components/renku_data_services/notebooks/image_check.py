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
from authlib.integrations.httpx_client import OAuthError

from renku_data_services.app_config import logging
from renku_data_services.base_models.core import APIUser
from renku_data_services.connected_services.db import ConnectedServicesRepository
from renku_data_services.connected_services.models import ImageProvider, OAuth2Client, OAuth2Connection
from renku_data_services.errors import errors
from renku_data_services.notebooks.api.classes.image import Image, ImageRepoDockerAPI
from renku_data_services.notebooks.config import NotebooksConfig
from renku_data_services.notebooks.oci.image_index import Platform
from renku_data_services.notebooks.oci.utils import get_image_platforms

logger = logging.getLogger(__name__)


@final
@dataclass(frozen=True)
class CheckResult:
    """Result of checking access to an image."""

    accessible: bool
    platforms: list[Platform] | None
    response_code: int
    image_provider: ImageProvider | None = None
    token: str | None = field(default=None, repr=False)
    error: errors.UnauthorizedError | None = None

    def __str__(self) -> str:
        token = "***" if self.token else "None"
        error = "unauthorized" if self.error else "None"
        return (
            "CheckResult("
            f"accessible={self.accessible}/{self.response_code}, "
            f"provider={self.image_provider}, token={token}, error={error})"
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


class ImageCheckRepository:
    """Repository for checking session images with rich responses."""

    def __init__(self, nb_config: NotebooksConfig, connected_services_repo: ConnectedServicesRepository) -> None:
        self.nb_config = nb_config
        self.connected_services_repo = connected_services_repo

    async def check_image(self, user: APIUser, gitlab_user: APIUser | None, image: Image) -> CheckResult:
        """Check access to the given image and provide image and access details."""
        reg_api: ImageRepoDockerAPI = image.repo_api()  # public images
        unauth_error: errors.UnauthorizedError | None = None
        image_provider = await self.connected_services_repo.get_provider_for_image(user, image)
        connected_user = image_provider.connected_user if image_provider is not None else None
        connection = connected_user.connection if connected_user is not None else None
        if image_provider is not None:
            try:
                reg_api = await self.connected_services_repo.get_image_repo_client(image_provider)
            except errors.UnauthorizedError as e:
                logger.info(f"Error getting image repo client for image {image}: {e}")
                unauth_error = e
            except OAuthError as e:
                logger.info(f"Error getting image repo client for image {image}: {e}")
                unauth_error = errors.UnauthorizedError(
                    message=f"OAuth error when getting repo client for image: {image}"
                )
                unauth_error.__cause__ = e
        elif gitlab_user and gitlab_user.access_token and image.hostname == self.nb_config.git.registry:
            logger.debug(f"Using internal gitlab at {self.nb_config.git.registry}")
            reg_api = reg_api.with_oauth2_token(gitlab_user.access_token)

        try:
            status_code, response = await reg_api.image_check(image, include_manifest=True)
        except httpx.HTTPError as e:
            logger.info(f"Error connecting {reg_api.scheme}://{reg_api.hostname}: {e}")
            status_code = 0
            response = None

        if status_code != 200 and connection is not None:
            try:
                await self.connected_services_repo.get_oauth2_connected_account(connection.id, user)
            except errors.UnauthorizedError as e:
                logger.info(f"Error getting connected account: {e}")
                unauth_error = e

        platforms = None
        if status_code == 200 and response is not None:
            platforms = await get_image_platforms(manifest_response=response, image=image, reg_api=reg_api)
        logger.info(f"Platforms: {platforms}")

        return CheckResult(
            accessible=status_code == 200,
            platforms=platforms,
            response_code=status_code,
            image_provider=image_provider,
            token=reg_api.oauth2_token,
            error=unauth_error,
        )
