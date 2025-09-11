"""Functions for checking access to images.

Access to docker images can fall into these cases:

1. The image is public and exists. It can be accessed anonymously
2. The image cannot be found. It may be absent or it requires credentials to access it

For the latter case, try to find out as much as possible:
- Look for credentials in the connected services
- If there are no connections defined for that user and registry, image is not accessible
- Try access it with the credentials:
  - a 404 means the image doesn't exist
  - a 402 means the credentials are not valid or don't provide enoug permissions to access it (access denied)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import final

from renku_data_services.app_config import logging
from renku_data_services.base_models.core import APIUser
from renku_data_services.connected_services.db import ConnectedServicesRepository
from renku_data_services.connected_services.models import OAuth2Connection
from renku_data_services.errors import errors
from renku_data_services.notebooks.api.classes.image import Image

logger = logging.getLogger(__name__)


@final
@dataclass(frozen=True)
class CheckResult:
    """Result of checking access to an image."""

    accessible: bool
    response_code: int
    connection: OAuth2Connection | None = None
    error: errors.UnauthorizedError | None = None


async def check_image_path(
    image_path: str, user: APIUser, connected_services: ConnectedServicesRepository
) -> CheckResult:
    """Check access to the given image."""
    image = Image.from_path(image_path)
    return await check_image(image, user, connected_services)


async def check_image(image: Image, user: APIUser, connected_services: ConnectedServicesRepository) -> CheckResult:
    """Check access to the given image."""

    logger.info(f"Get docker client for user={user} and image={image}")
    reg_api, conn_id = await connected_services.get_docker_client(user, image)

    if reg_api is None:
        logger.info(f"Using public registry api for image {image.name}")
        reg_api = image.repo_api()
    else:
        logger.info(f"Found docker client for connection {conn_id}")

    result = await reg_api.image_check(image)
    unauth_error: errors.UnauthorizedError | None = None
    if result != 200 and conn_id is not None:
        try:
            await connected_services.get_oauth2_connected_account(conn_id, user)
        except errors.UnauthorizedError as e:
            unauth_error = e

    conn = await connected_services.get_oauth2_connection(conn_id, user) if conn_id is not None else None
    return CheckResult(accessible=result == 200, response_code=result, connection=conn, error=unauth_error)
