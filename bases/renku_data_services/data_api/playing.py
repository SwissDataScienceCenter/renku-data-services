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


admin = APIUser(
    id="16ad1834-0e94-4b68-8d6d-f39961ff555d",
    is_admin=True,
    first_name="Armin",
    last_name="A",
    access_token="blabla",
)


async def create_test_users() -> None:
    """Create my test users."""
    await create_user("46ee17f0-e689-47d8-9747-5517f1f8440f", "Eike", "K", False)
    await create_user("77b45c0a-7e3c-400c-a0cf-8bcd1dc0e53f", "James", "B", False)
    await create_user("16ad1834-0e94-4b68-8d6d-f39961ff555d", "Armin", "A.", True)


async def gh_image_token(gh_token: str) -> None:
    """Bla."""
    gh_name = "ghcr.io/eikek/privim"
    gh_image = Image.from_path(gh_name)
    reg_api = gh_image.repo_api().with_oauth2_token(gh_token)
    token = await reg_api._get_docker_token(gh_image)
    print(token)


async def gl_image_token(gl_token: str) -> None:
    """Bla."""
    gl_name = "registry.gitlab.com/eikek1/privim"
    gl_image = Image.from_path(gl_name)
    #    token = base64.b64encode(f"eikek1:{gl_token}".encode()).decode()
    #    print(token)
    reg_api = gl_image.repo_api().with_oauth2_token(gl_token).with_oauth2_user("eikek1")
    token = await reg_api._get_docker_token(gl_image)
    print(token)


async def dh_image_token() -> None:
    dh_name = "docspell/restserver"
    dh_image = Image.from_path(dh_name)
    reg_api = dh_image.repo_api()  # .with_oauth2_token(gh_token)
    token = await reg_api._get_docker_token(dh_image)
    print(token)


async def check_image(image_name: str, token: str | None, user: str | None) -> None:
    image = Image.from_path(image_name)

    reg_api, conn_id = await deps.connected_services_repo.get_docker_client(admin, image)

    if reg_api is None:
        print("Using public registry api…")
        reg_api = image.repo_api()
        reg_api = reg_api.with_oauth2_token(token) if token is not None else reg_api
        reg_api = reg_api.with_oauth2_user(user) if user is not None else reg_api

    result = await reg_api.image_check(image)
    print(f"{image_name}: {result}")


async def check_docker_image(gh_token: str, gl_token: str) -> None:
    """The bla."""

    # dockerhub always reports 401 for non existent images
    # await check_image("docspell/restserver", None, None)
    await check_image("eikek0/privim2", "", None)

    # github uses 404 for non existent
    # await check_image("ghcr.io/eikek/privim", gl_token, None)
    # await check_image("registry.gitlab.com/eikek/privim", gl_token, "eikek1")


## method:


if __name__ == "__main__":
    gh_token = os.getenv("GHCR_TOKEN") or ""
    gl_token = os.getenv("GLAB_TOKEN") or ""
    asyncio.run(check_docker_image(gh_token, gl_token))
#    asyncio.run(check_docker_image(gh_token, gl_token))
