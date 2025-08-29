"""Just playing around."""

import asyncio
import os

from renku_data_services.base_models.core import APIUser
from renku_data_services.data_api.dependencies import DependencyManager
from renku_data_services.notebooks.api.classes.image import Image

deps = DependencyManager.from_env()


async def create_user(id: str, fname: str, lname: str, admin: bool) -> None:
    """Create a user."""
    api_user = APIUser(id=id, is_admin=admin, first_name=fname, last_name=lname)
    await deps.kc_user_repo.get_or_create_user(requested_by=api_user, id=id)


async def create_test_users() -> None:
    """Create my test users."""
    await create_user("46ee17f0-e689-47d8-9747-5517f1f8440f", "Eike", "K", False)
    await create_user("77b45c0a-7e3c-400c-a0cf-8bcd1dc0e53f", "James", "B", False)


async def check_docker_image(gh_token: str, gl_token: str) -> None:
    """The bla."""
    gh_name = "ghcr.io/eikek/privim"
    gl_name = "registry.gitlab.com/eikek1/privim"

    gh_image = Image.from_path(gh_name)
    gl_image = Image.from_path(gl_name)
    gh_manifest = (
        await gh_image.repo_api().maybe_with_oauth2_token(gh_image.hostname, gh_token).get_image_manifest(gh_image)
    )
    gl_manifest = (
        await gl_image.repo_api().maybe_with_oauth2_token(gl_image.hostname, gl_token).get_image_manifest(gl_image)
    )

    print(f"GitHub: {gh_manifest}")
    print(f"GitLab: {gl_manifest}")


## method:


if __name__ == "__main__":
    gh_token = os.getenv("GHCR_TOKEN") or ""
    gl_token = os.getenv("GLAB_TOKEN") or ""
    asyncio.run(check_docker_image(gh_token, gl_token))
