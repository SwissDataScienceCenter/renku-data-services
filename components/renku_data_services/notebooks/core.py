"""Notebooks service core implementation, specifically for JupyterServer sessions."""

from pathlib import PurePosixPath

from renku_data_services.app_config import logging
from renku_data_services.base_models import APIUser
from renku_data_services.notebooks.api.classes.image import Image
from renku_data_services.notebooks.config import NotebooksConfig

logger = logging.getLogger(__name__)


async def docker_image_exists(config: NotebooksConfig, image_url: str, internal_gitlab_user: APIUser) -> bool:
    """Returns whether the passed docker image url exists.

    If the user is logged in the internal GitLab (Renku V1), set the
    credentials for the check.
    """

    parsed_image = Image.from_path(image_url)
    image_repo = parsed_image.repo_api().maybe_with_oauth2_token(config.git.registry, internal_gitlab_user.access_token)
    return await image_repo.image_exists(parsed_image)


async def docker_image_workdir(
    config: NotebooksConfig, image_url: str, internal_gitlab_user: APIUser
) -> PurePosixPath | None:
    """Returns the working directory for the image.

    If the user is logged in the internal GitLab (Renku V1), set the
    credentials for the check.
    """

    parsed_image = Image.from_path(image_url)
    image_repo = parsed_image.repo_api().maybe_with_oauth2_token(config.git.registry, internal_gitlab_user.access_token)
    return await image_repo.image_workdir(parsed_image)
